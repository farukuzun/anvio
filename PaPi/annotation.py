# -*- coding: utf-8

# Copyright (C) 2014, A. Murat Eren
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of the GNU General Public License as published by the Free
# Software Foundation; either version 2 of the License, or (at your option)
# any later version.
#
# Please read the COPYING file.

"""
    Here is described the annotation class. Any parser implemented in parsers.py must generate headers
    matching 'header' variable.
"""

annotation_table_structure = ['prot', 'contig', 'start', 'stop'   , 'direction', 'figfam', 'function', "t_phylum", "t_class", "t_order", "t_family", "t_genus", "t_species"]
annotation_table_mapping   = [ str  ,   str   ,  int   ,   int    ,     str    ,   str   ,    str    ,    str    ,   str    ,    str   ,    str    ,    str   ,     str    ]
annotation_table_types     = ['text',  'text' ,'numeric','numeric',   'text'   ,  'text' ,   'text'  ,   'text'  ,  'text'  ,  'text'  ,  'text'   ,  'text'  ,   'text'   ]

splits_table_structure = ['split', 'taxonomy', 'num_genes', 'avg_gene_length', 'ratio_coding', 'ratio_hypothetical', 'ratio_with_tax', 'tax_accuracy']
splits_table_mapping   = [  str  ,     str   ,    int     ,       float      ,    'float'    ,        float        ,       float     ,     float     ]
splits_table_types     = [ 'text',   'text'  ,  'numeric' ,     'numeric'    ,   'numeric'   ,      'numeric'      ,     'numeric'   ,   'numeric'   ]

__version__ = "0.0.1"

import os
import sys
import numpy
import operator
from collections import Counter

import PaPi.db as db
import PaPi.fastalib as u
import PaPi.utils as utils
import PaPi.dictio as dictio
import PaPi.filesnpaths as filesnpaths
from PaPi.utils import ConfigError
from PaPi.contig import Split


class Annotation:
    def __init__(self, db_path):
        self.db_path = db_path
        self.db = None

        # a dictionary to keep contigs
        self.contigs = {}
        self.split_length = None


    def create_new_database(self, contigs_fasta, source, split_length, parser="unknown"):
        if type(source) == type(dict()):
            self.matrix_dict = source
            self.check_keys(['prot'] + self.matrix_dict.values()[0].keys())
        if type(source) == type(str()):
            self.matrix_dict = utils.get_TAB_delimited_file_as_dictionary(source,
                                                                          column_names = annotation_table_structure,
                                                                          column_maping = annotation_table_mapping)

        # populate contigs dict with contig lengths
        fasta = u.SequenceSource(contigs_fasta)
        while fasta.next():
            self.contigs[fasta.id] = {'length': len(fasta.seq)}

        self.sanity_check()

        # init a new db
        self.db = db.DB(self.db_path, __version__, new_database = True)

        # set split length variable in the meta table
        self.db.set_meta_value('split_length', split_length)
        self.db.set_meta_value('annotation_source', parser)
        self.split_length = split_length

        # create annotation main table using fields in 'annotation_table_structure' variable
        self.db.create_table('annotation', annotation_table_structure, annotation_table_types)

        # push raw entries.
        db_entries = [tuple([prot] + [self.matrix_dict[prot][h] for h in annotation_table_structure[1:]]) for prot in self.matrix_dict]
        self.db._exec_many('''INSERT INTO annotation VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''', db_entries)

        # compute and push split taxonomy information.
        self.init_splits_table()

        # bye.
        self.db.disconnect()


    def sanity_check(self):
        contig_names_in_matrix = set([v['contig'] for v in self.matrix_dict.values()])
        contig_names_in_fasta  = set(self.contigs.keys())

        for contig in contig_names_in_matrix:
            if contig not in contig_names_in_fasta:
                raise ConfigError, "We have a problem... Every contig name there is in your input files for annotation\
                                    must be found in the FASTA file. But it seems it is not the case. I did not check\
                                    all, but there there is at least one contig name ('%s') that appears in the\
                                    annotation files, but missing in the FASTA file. You may need to format the\
                                    names in your FASTA file to match contig names in your annotation files. Keep in\
                                    mind that contig names must match the ones in your BAM files later on. Even when\
                                    you use one software for assembly and mapping, disagreements between contig names\
                                    may arise. We know that it is the case with CLC, for instance. OK. Going back to the\
                                    issue. Here is one contig name from your FASTA file: '%s', and here is one from your\
                                    input files: '%s'. You should make them identical (and make sure whatever solution\
                                    you come up with will not make them incompatible with names in your BAM files\
                                    later on." % (contig, contig_names_in_fasta.pop(), contig_names_in_matrix.pop())


    def init_database(self):
        self.db = db.DB(self.db_path, __version__)


    def check_keys(self, keys):
        missing_keys = [key for key in annotation_table_structure if key not in keys]
        if len(missing_keys):
            raise ConfigError, "Your input lacks one or more header fields to generate a PaPi annotation db. Here is\
                                what you are missing: %s. The complete list (and order) of headers in your TAB\
                                delimited matrix file (or dictionary) must follow this: %s." % (', '.join(missing_keys),
                                                                                                ', '.join(annotation_table_structure))


    def init_splits_table(self):
        # build a dictionary for fast access to all proteins identified within a contig
        prots_in_contig = {}
        for prot in self.matrix_dict:
            contig = self.matrix_dict[prot]['contig']
            if prots_in_contig.has_key(contig):
                prots_in_contig[contig].add(prot)
            else:
                prots_in_contig[contig] = set([prot])

        splits_dict = {}
        for contig in self.contigs:
            chunks = utils.get_chunks(self.contigs[contig]['length'], self.split_length)
            for i in range(0, len(chunks)):
                split = Split(contig, i).name
                start = chunks[i][0]
                stop = chunks[i][1]

                taxa = []
                functions = []
                gene_start_stops = []
                for prot in prots_in_contig[contig]:
                    if self.matrix_dict[prot]['stop'] > start and self.matrix_dict[prot]['start'] < stop:
                        taxa.append(self.matrix_dict[prot]['t_species'])
                        functions.append(self.matrix_dict[prot]['function'])
                        gene_start_stops.append((self.matrix_dict[prot]['start'], self.matrix_dict[prot]['stop']), )

                taxonomy_strings = [t for t in taxa if t]
                function_strings = [f for f in functions if f]

                # here we identify genes that are associated with a split even if one base of the gene spills into 
                # the defined start or stop of a split, which means, split N, will include genes A, B and C in this
                # scenario:
                #
                # contig: (...)------[ gene A ]--------[     gene B    ]----[gene C]---------[    gene D    ]-----(...)
                #         (...)----------x---------------------------------------x--------------------------------(...)
                #                        ^ (split N start)                       ^ (split N stop)
                #                        |                                       |
                #                        |<-              split N              ->|
                #
                # however, when looking at the coding versus non-coding nucleotide ratios in a split, we have to make
                # sure that only the relevant portion of gene A and gene C is counted:
                total_coding_nts = 0
                for gene_start, gene_stop in gene_start_stops:
                    total_coding_nts += (gene_stop if gene_stop < stop else stop) - (gene_start if gene_start > start else start)

                splits_dict[split] = {'taxonomy': None,
                                      'num_genes': len(taxa),
                                      'avg_gene_length': numpy.mean([(l[1] - l[0]) for l in gene_start_stops]),
                                      'ratio_coding': total_coding_nts * 1.0 / (stop - start),
                                      'ratio_hypothetical': (len(functions) - len(function_strings)) * 1.0 / len(functions) if len(functions) else 0.0,
                                      'ratio_with_tax': len(taxonomy_strings) * 1.0 / len(taxa) if len(taxa) else 0.0,
                                      'tax_accuracy': 0.0}

                distinct_taxa = set(taxonomy_strings)

                if not len(distinct_taxa):
                    continue

                if len(distinct_taxa) == 1:
                    splits_dict[split]['taxonomy'] = distinct_taxa.pop()
                    splits_dict[split]['tax_accuracy'] = 1.0
                else:
                    d = Counter()
                    for taxon in taxonomy_strings:
                        d[taxon] += 1
                    consensus, occurrence = sorted(d.items(), key=operator.itemgetter(1))[-1]
                    splits_dict[split]['taxonomy'] = consensus
                    splits_dict[split]['tax_accuracy'] = occurrence * 1.0 / len(taxonomy_strings)

        # create splits table using fields in 'splits_table_structure' info
        self.db.create_table('splits', splits_table_structure, splits_table_types)

        # push raw entries.
        db_entries = [tuple([split] + [splits_dict[split][h] for h in splits_table_structure[1:]]) for split in splits_dict]
        self.db._exec_many('''INSERT INTO splits VALUES (?,?,?,?,?,?,?,?)''', db_entries)


    def get_consensus_taxonomy_for_split(self, contig, t_level = 't_species', start = 0, stop = sys.maxint):
        """Returns (c, n, t, o) where,
            c: consensus taxonomy (the most common taxonomic call for each gene found in the contig),
            n: total number of genes found in the contig,
            t: total number of genes with known taxonomy,
            o: number of taxonomic calls that matches the consensus among t
        """

        response = self.db.cursor.execute("""SELECT %s FROM annotation WHERE contig='%s' and stop > %d and start < %d""" % (t_level, contig, start, stop))
        rows = response.fetchall()

        num_genes = len(rows)
        tax_str_list = [t[0] for t in rows if t[0]]
        distinct_taxa = set(tax_str_list)

        if not len(distinct_taxa):
            return None, num_genes, 0, 0

        if len(distinct_taxa) == 1:
            return distinct_taxa.pop(), num_genes, len(tax_str_list), len(tax_str_list)
        else:
            d = Counter()
            for t in tax_str_list:
                d[t] += 1
            consensus, occurrence = sorted(d.items(), key=operator.itemgetter(1))[-1]
            return consensus, num_genes, len(tax_str_list), occurrence