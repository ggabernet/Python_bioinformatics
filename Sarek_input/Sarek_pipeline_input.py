# Generating input file for variant calling using the Sarek Pipeline
# Gisela Gabernet | QBiC | November 2018

import pandas as pd
import re
import subprocess
import sys
import csv
import argparse

# Static functions


def _pretty_tree(d, f, indent=0):
    for key, value in d.items():
        f.write('\t' * indent + '|_' + str(key) + '\n')
        if isinstance(value, dict):
            _pretty_tree(value, f, indent + 1)
        else:
            f.write('\t' * (indent + 1) + str(value) + '\n')


def write_tree(d, fname):
    with open(fname, 'w') as f:
        _pretty_tree(d, f)


# Class
class SelectVariantCalling:

    def __init__(self, project):
        """
        Initiates instance of SelectVariantCalling class.
        :param project: [str] project QBiC code.
        """
        self.project = project
        self.VC_table = pd.DataFrame()
        self.fastq_paths = []
        self.tree = dict()
        self.code_pattern = re.compile(self.project + '[A-Z0-9]{4}[A-Z0-9-_]{0,6}')
        self.input_df = pd.DataFrame()
        self.fastq = []

    def create_VC_table(self, experiment_tsv, sample_tsv):
        """
        Reads experiment and sample tsv tables and processes them and merges them to produce a dataframe of DNA samples
        ready for extracting the information for variant calling analysis.
        :param experiment_tsv: [file .tsv] all experiments for the project as extracted from the openBIS database.
        :param sample_tsv: [file .tsv] all samples for the project as extracted from the openBIS database.
        :return: Variant calling data table as pandas dataframe in attribute VC_table
        """
        exp_df = pd.read_csv(experiment_tsv, sep='\t')
        sample_df = pd.read_csv(sample_tsv, sep='\t')

        sample_df = sample_df[sample_df.loc[:, 'Project'] == self.project]

        ngs_df = sample_df[sample_df.loc[:, 'Sample Type'] == 'Q_NGS_SINGLE_SAMPLE_RUN']
        ngs_df.columns = ["NGS_sample_" + i for i in ngs_df.columns]
        ngs_df.loc[:, 'NGS_sample_Parents_code'] = [self.code_pattern.search(str(row)).group(0)
                                                    if self.code_pattern.search(str(row)) else '' for row in
                                                    ngs_df.loc[:, 'NGS_sample_Parents']]
        if ngs_df[ngs_df.loc[:, 'NGS_sample_Parents_code'] == ''].shape[0] > 0:
            print "These samples do not have parents and won't be considered:"
            print ngs_df[ngs_df.loc[:, 'NGS_sample_Parents_code'] == ''].loc[:, 'NGS_sample_Code'].tolist()

        test_df = sample_df[sample_df['Sample Type'] == 'Q_TEST_SAMPLE']
        test_df.columns = ["Test_sample_" + i for i in test_df.columns]
        test_df.loc[:, 'Test_sample_Parents_code'] = [self.code_pattern.search(str(row)).group(0)
                                                      if self.code_pattern.search(str(row)) else '' for row in
                                                      test_df.loc[:, 'Test_sample_Parents']]
        test_df.head()
        if test_df[test_df['Test_sample_Parents_code'] == ''].shape[0] > 0:
            print "These samples do not have parents and won't be considered:"
            print test_df[test_df['Test_sample_Parents_code'] == '']

        biol_df = sample_df[sample_df['Sample Type'] == 'Q_BIOLOGICAL_SAMPLE']
        biol_df.columns = ["Biol_sample_" + i for i in biol_df.columns]
        biol_df.loc[:, 'Biol_sample_Parents_code'] = [self.code_pattern.search(str(row)).group(0)
                                                      if self.code_pattern.search(str(row)) else '' for row in
                                                      biol_df.loc[:, 'Biol_sample_Parents']]
        biol_df.head()
        if biol_df[biol_df['Biol_sample_Parents_code'] == ''].shape[0] > 0:
            print "These samples do not have parents and won't be considered:"
            print biol_df[biol_df['Biol_sample_Parents_code'] == '']

        exp_df = exp_df[exp_df['Experiment Type'] == 'Q_NGS_MEASUREMENT']
        exp_df.columns = ["Exp_" + i for i in exp_df.columns]

        ngs_exp_df = ngs_df.merge(exp_df, how='left', left_on='NGS_sample_Experiment',
                                  right_on='Exp_Code', suffixes=('', ''))
        ngs_exp_test_df = ngs_exp_df.merge(test_df, how='left', left_on='NGS_sample_Parents_code',
                                           right_on='Test_sample_Code',
                                           suffixes=('', ''))
        ngs_exp_test_biol_df = ngs_exp_test_df.merge(biol_df, how='left', left_on='Test_sample_Parents_code',
                                                     right_on='Biol_sample_Code', suffixes=('', ''))
        biol_entity_df = pd.DataFrame({'BS_code': biol_df['Biol_sample_Code'],
                                       'Entity': biol_df['Biol_sample_Parents_code']})

        # Sometimes biological samples have as parents another biological sample. Solve this by searching their parents
        ngs_exp_test_biol_entity_df = ngs_exp_test_biol_df.merge(biol_entity_df, how='left',
                                                                 left_on='Biol_sample_Parents_code',
                                                                 right_on='BS_code', suffixes=('', ''))
        ngs_exp_test_biol_entity_df.head()
        ngs_exp_test_biol_entity_df.loc[:, 'Entity'] = [
            ngs_exp_test_biol_entity_df.loc[i, 'Biol_sample_Parents_code'] if pd.isna(row)
            else ngs_exp_test_biol_entity_df.loc[i, 'Entity']
            for (i, row) in enumerate(ngs_exp_test_biol_entity_df.loc[:, 'Entity'])]

        # Renaming merged dataframe
        data_df = ngs_exp_test_biol_entity_df
        print 'Created merged data frame. Rows:', data_df.shape[0], ', Cols:', data_df.shape[1]

        # Dropping columns where all values are NaN
        data_df = data_df.dropna(axis=1, how='all')
        print 'Eliminated empty columns. Rows:', data_df.shape[0], ', Cols:', data_df.shape[1]

        # Dropping rows where tissue is NaN (can't determine if tumor or not)
        data_df = data_df.dropna(axis=0, how='any', subset=['Biol_sample_Primary tissue/body fluid'])
        print 'Eliminated rows with no tissue annotation. Rows:', data_df.shape[0], 'Cols:', data_df.shape[1]

        # Annotating if tumor
        # TODO: give possibility of changing tumor regex
        tumor_name = re.compile('[Tt][uU][mM][oO][rR]')
        data_df['IsTumor'] = [1 if bool(re.search(tumor_name, row)) else 0 for row in
                              data_df.loc[:, 'Biol_sample_Primary tissue/body fluid']]
        data_df['Status'] = ['Tumor' if row == 1 else 'Normal' for row in data_df.loc[:, 'IsTumor']]
        data_df.head()
        print 'Added boolean tumor annotation. Rows:', data_df.shape[0], 'Cols:', data_df.shape[1]

        # Annotating VC name
        data_df.loc[:, 'VC_name'] = data_df.loc[:, 'Test_sample_Code']

        # Selecting only DNA test samples
        data_dna_df = data_df[data_df['Test_sample_Sample type'] == 'DNA [DNA]']
        print 'Selected only DNA samples. Rows:', data_dna_df.shape[0], 'Cols:', data_dna_df.shape[1]

        # Defining path
        data_dna_df.loc[:, 'VCpath'] = [i + '/' + j + '/' + k + '/' + l + '/' for i, j, k, l in
                                        zip(data_dna_df.loc[:, 'Entity'], data_dna_df.loc[:, 'Biol_sample_Code'],
                                            data_dna_df.loc[:, 'Status'], data_dna_df.loc[:, 'Test_sample_Code'])]
        self.fastq_paths = data_dna_df.loc[:, 'VCpath'].tolist()
        self.VC_table = data_dna_df

    def print_tree(self, file_name='tree.txt'):
        """
        Print tree structure of VC table in tree form. Requires usage of create_VC_table first
        :param file_name: [str] file name where to print the tree.
        :return: tree in the form of a nested dictionary in tree attribute and printed tree in the specified file
        ('tree.txt' by default).
        """

        # Creating tree
        child_status = self.VC_table.loc[:, 'Status'].tolist()
        parent_status = self.VC_table.loc[:, 'NGS_sample_Code'].tolist()

        child_NGS = self.VC_table.loc[:, 'NGS_sample_Code'].tolist()
        parent_NGS = self.VC_table.loc[:, 'NGS_sample_Parents_code'].tolist()

        child_test = self.VC_table.loc[:, 'Test_sample_Code'].tolist()
        parent_test = self.VC_table.loc[:, 'Test_sample_Parents_code'].tolist()

        child_biol = self.VC_table.loc[:, 'Biol_sample_Code'].tolist()
        parent_biol = self.VC_table.loc[:, 'Biol_sample_Parents_code'].tolist()

        child_entity = self.VC_table.loc[:, 'Biol_sample_Parents_code'].tolist()
        parent_entity = self.VC_table.loc[:, 'Biol_sample_Project'].tolist()

        child = child_status + child_NGS + child_test + child_biol + child_entity
        parent = parent_status + parent_NGS + parent_test + parent_biol + parent_entity

        child_parent = zip(child, parent)

        items = {}
        for (child, parent) in child_parent:
            parent_dict = items.setdefault(parent, {})
            child_dict = items.setdefault(child, {})
            if child not in parent_dict:
                parent_dict[child] = child_dict

        tree_dict = items[self.project]

        write_tree(tree_dict, file_name)

        self.tree = tree_dict

        return

    def organize_dirs(self, path=".", file_name_contains='Test'):
        """
        Generating directory paths and organizing files into directories
        :param path: [str] path of the directory containing the fastq files.
        :param file_name_contains: [str] Which kind of identifier needs to be searched in the fastq files.
                        Choose from: 'Test' (QBiC test sample code), 'Secondary_name' (IMGAG sample code
                        stored in the Secondary name field).
        :return:
        """

        if file_name_contains == 'Test':
            fname_col = 'Test_sample_Code'
        elif file_name_contains == 'Secondary_name':
            fname_col = 'NGS_sample_Secondary name'
        else:
            sys.exit('Invalid file_name_contains paramter, choose from ["Test", "Secondary_name"].\n')

        subprocess.call("cd %s" % path, shell=True, stdout=True)

        # Generating folders and sorting fastq files into folders
        for name, npath in zip(self.VC_table.loc[:, fname_col], self.VC_table.loc[:, 'VCpath'].tolist()):
            subprocess.call("mkdir -p %s" % npath, shell=True, stdout=True)
            subprocess.Popen("mv %s* %s" % (name, npath), shell=True, stdout=True)

        code_pattern = subprocess.Popen("find `pwd` -name '*.fastq.gz'", shell=True, stdout=subprocess.PIPE)
        out, err = code_pattern.communicate()
        fastqfiles = out.split("\n")
        self.fastq = sorted(fastqfiles)
        return

    def generate_input_file(self, patternR1='_R1_', patternR2='_R2_',
                            pattern_lane='_L[0-9]{3}[_\.]'):
        """
        Generating input file
        :param patternR1: [str, regex] regular expression for fastq files pair 1.
        :param patternR2: [str, regex] regular expression for fastq files pair 2.
        :param pattern_lane: [str, regex] regular expression for lane indexes.
        :return: saves input file
        """
        p_R1 = re.compile(patternR1)
        p_R2 = re.compile(patternR2)
        p_lane = re.compile(pattern_lane)

        # Separating R1 and R2 fastq files
        fastqfiles = self.fastq

        fasta_R1 = [filename if bool(re.search(p_R1, filename)) else '' for filename in fastqfiles]
        fasta_R2 = [filename if bool(re.search(p_R2, filename)) else '' for filename in fastqfiles]

        fasta_R1 = filter(None, sorted(fasta_R1))
        fasta_R2 = filter(None, sorted(fasta_R2))

        if len(fasta_R1) != len(fasta_R2):
            sys.exit("The fasta files were not correctly paired, different number of R1 and R2.")

        # Searching for lanes
        # TODO: add test for if lanes is empty give always same lane.
        fasta_lanes = [re.search(p_lane, filename).group(0) for filename in fasta_R1]

        filenames_df = pd.DataFrame({'Lane': fasta_lanes, 'Fasta_R1': fasta_R1, 'Fasta_R2': fasta_R2})

        test_codes = []
        for n, path in enumerate(self.VC_table['VCpath'].tolist()):
            idx = [bool(re.search(path, filename)) for filename in filenames_df['Fasta_R1']]
            test_codes = test_codes + [self.VC_table.loc[n, 'Test_sample_Code']] * sum(idx)

        filenames_df['Codes'] = test_codes
        # TODO: sex is currently hard-coded
        filenames_df['Sex'] = ['XY'] * len(test_codes)

        VC_table_input = self.VC_table.merge(filenames_df, how='right',
                                              left_on='Test_sample_Code', right_on='Codes', suffixes=('', ''))
        # TODO: VC_name is not needed
        VC_table_input = VC_table_input[['Entity', 'Sex', 'IsTumor', 'Codes', 'Lane', 'Fasta_R1', 'Fasta_R2']]
        self.input_df = VC_table_input
        return self

    def write_input_file(self, file_name = 'Sarek_pipeline_input.txt'):
        """
        Write input table to file.
        :param file_name: [str] file name where to store the table.
        :return: input_df saved in file_name.
        """
        self.input_df.to_csv(file_name, sep='\t', header=False, index=False, quoting=csv.QUOTE_NONE, quotechar='',
                             doublequote=False)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("project", type=str, help="QBiC project code for which VC should be calculated.")
    parser.add_argument("sample_tsv", type=str, help="Path to the sample table tsv file extracted from OpenBIS.")
    parser.add_argument("experiment_tsv", type=str, help="Path to the experiment table tsv file extracted from OpenBIS.")
    parser.add_argument("-p", "--path", type=str, default=".", help="Path to folder with fastq files.")
    parser.add_argument("-c", "--contains", type=str, choices=['Test', 'Secondary_name'], default='Test',
                        help="String of the identifier that is contained in the fastq filename.\n "
                             "'Test' stands for QBiC test sample code.\n"
                             "'Secondary_name' stands for NGS sample secondary name "
                             "(usu. Genetics ID).")
    parser.add_argument("-pR1", "--patternR1", type=str, default='_R1_', help="Regex to look for at fastq filename and "
                                                                              "identify 1st fastq of a pair.")
    parser.add_argument("-pR2", "--pattern_R2", type=str, default='_R2_', help="Regex to look for at fastq filename "
                                                                               "and identify 2nd fastq of a pair.")
    parser.add_argument("-pL", "--pattern_lane", type=str, default='_L[0-9]{3}[_\.]', help="Regex to look for at fastq"
                                                                                           "filename to identify"
                                                                                           "sequencing lane.")
    parser.add_argument("-f", "--filename", type=str, default="Sarek_input.tsv", help="File name for Sarek input table.")
    args = parser.parse_args()


    inst = SelectVariantCalling(args.project)
    inst.create_VC_table(args.experiment_tsv, args.sample_tsv)
    inst.print_tree()
    inst.organize_dirs(args.path, args.contains)
    inst.generate_input_file(args.patternR1, args.patternR2, args.pattern_lane)
    inst.write_input_file(args.filename)
