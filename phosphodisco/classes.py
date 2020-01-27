from pandas import DataFrame, Series
import numpy as np
import pandas as pd
import logging
from typing import Iterable, Optional
from itertools import product
from statsmodels.stats.multitest import multipletests
import hypercluster
from hypercluster.constants import param_delim, val_delim
from .utils import norm_line_to_residuals
from .constants import module_combiner_delim, annotation_column_map
from .annotation_association import (
    corr_na, binarize_categorical, continuous_score_association, categorical_score_association
)
from .nominate_regulators import collapse_putative_regulators, calculate_regulator_coefficients



class ProteomicsData:
    def __init__(
            self,
            phospho: DataFrame,
            protein: DataFrame,
            min_common_values: Optional[int] = 5,
            normed_phospho: Optional[DataFrame] = None,
            categorical_annotations: Optional[DataFrame] = None,
            continuous_annotations: Optional[DataFrame] = None,
            modules: Optional[Iterable] = None,
            clustering_parameters_for_modules: Optional[dict] = None,
            putative_regulator_list: Optional[list] = None,
            putative_regulator_data: Optional[DataFrame] = None,
            module_scores: Optional[DataFrame] = None,
            anticorrelated_collapsed: Optional[bool] = None,
            regulator_coefficients: Optional[DataFrame] = None
    ):
        self.min_values_in_common = min_common_values

        common_prots = list(set(phospho.index.get_level_values(0).intersection(protein.index)))
        common_samples = phospho.columns.intersection(protein.columns)
        self.phospho = phospho[common_samples]
        self.protein = protein[common_samples]
        self.categorical_annotations = categorical_annotations
        self.continuous_annotations = continuous_annotations
        self.common_prots = common_prots
        self.common_samples = common_samples
        self.clustering_parameters_for_modules = clustering_parameters_for_modules
        self.putative_regulator_list = putative_regulator_list
        self.putative_regulator_data = putative_regulator_data

        logging.info('Phospho and protein data have %s proteins in common' % len(common_prots))
        logging.info(
            'Phospho and protein data have %s samples in common, re-indexed to only common '
            'samples.' % len(common_samples)
        )

        common_phospho = self.phospho.loc[common_prots,:]
        common_prot = self.protein.reindex(common_phospho.index.get_level_values(0))
        common_prot.index = common_phospho.index

        normalizable_rows = common_phospho.index[
            ((common_phospho.notnull() & common_prot.notnull()).sum(axis=1) >= min_common_values)
            ]

        self.normalizable_rows = normalizable_rows
        logging.info(
            'There are %s rows with at least %s non-null values in both phospho and protein' % (
                len(normalizable_rows), min_common_values
            )
        )
        self.normed_phospho = normed_phospho
        self.modules = modules
        self.anticorrelated_collapsed = anticorrelated_collapsed
        self.module_scores = module_scores
        self.regulator_coefficients = regulator_coefficients

    def normalize_phospho_by_protein(self, ridge_cv_alphas: Optional[Iterable] = None):
        if self.normed_phospho is not None:
            logging.warning('Overwriting protein-normalized phospho abundances. ')
        # TODO test this, make sure datatype_label goes away.
        target = self.phospho.loc[self.normalizable_rows]
        features = self.protein.reindex(target.index.get_level_values(0))
        features.index = target.index
        target = target.transpose()
        features = features.transpose()

        datatype_label = 'datatype_label'
        target[datatype_label] = 0
        features[datatype_label] = 1

        data = target.append(features)
        data = data.set_index(datatype_label, append=True)
        data.index = data.index.swaplevel(0, 1)
        data = data.transpose()

        residuals = data.apply(
            lambda row: norm_line_to_residuals(
                row[0], row[1], ridge_cv_alphas, self.min_values_in_common
            ), axis=1
        )

        self.normed_phospho = residuals
        return self

    def assign_modules(
            self,
            modules: Optional[DataFrame] = None,
            method_to_pick_best_labels: Optional[str] = None,
            min_or_max: Optional[str] = None,
            **multiautocluster_kwargs
    ):
        if modules is not None:
            self.modules = modules
        if self.modules is None:
            modules = hypercluster.MultiAutoClusterer(
                **multiautocluster_kwargs
            ).fit(self.normed_phospho).pick_best_labels(method_to_pick_best_labels, min_or_max)
            self.modules = modules

        if self.modules.shape[1] > 1:
            raise ValueError(
                'Too many sets of labels in ProteomicsData.modules, please reassign '
                'ProteomicsData.modules with a DataFrame with 1 column of labels.'
            )
        self.modules = modules[modules.columns[0]]

        parameters = self.modules.name.split(param_delim)
        clss = parameters.pop(0)
        parameters.append('clusterer%s%s' % (val_delim, clss))
        parameters = {s.split(val_delim, 1)[0]: s.split(val_delim, 1)[1] for s in parameters}
        self.clustering_parameters_for_modules = parameters
        return self

    def calculate_module_scores(
            self,
            combine_anti_regulated: bool = True,
            anti_corr_threshold: float = 0.9
    ):
        abundances = self.normed_phospho.reindex(self.modules.index)
        scores = abundances.groupby(self.modules).agg('mean')

        if combine_anti_regulated:
            corr = {
                (ind1, ind2): corr_na(scores.loc[ind1, :], scores.loc[ind2, :])[0]
                for ind1, ind2 in product(scores.index, scores.index)
                if -corr_na(scores.loc[ind1, :], scores.loc[ind2, :])[0] > anti_corr_threshold
            }
            if corr:
                for clusters_labs in corr.keys():
                    nmems = {k: self.nmembers_per_cluster[k] for k in clusters_labs}
                    major_cluster = max(nmems, key=lambda key: nmems[key])
                    minor_cluster = set(clusters_labs).difference({major_cluster})
                    line = (scores.loc[major_cluster, :] * nmems[major_cluster]).subtract(
                        (scores.loc[minor_cluster, :] * nmems[minor_cluster])
                    ).divide((nmems[major_cluster] + nmems[minor_cluster]))
                    line.name = module_combiner_delim.join(clusters_labs)
                    scores = scores.drop(clusters_labs, axis=0).append(line)

        self.anticorrelated_collapsed = combine_anti_regulated
        self.module_scores = scores.transpose()
        return self

    def collect_putative_regulators(self, possible_regulator_list, corr_threshold: float = 0.9):
        self.putative_regulator_list = possible_regulator_list
        subset = self.protein.loc[possible_regulator_list, :]
        subset[1] = np.nan
        subset = subset.set_index(1, append=True)
        putative_regulator_data = subset.append(self.phospho.loc[possible_regulator_list, :])
        putative_regulator_data = collapse_putative_regulators(
            putative_regulator_data, corr_threshold
        )
        self.putative_regulator_data = putative_regulator_data
        return self

    def calculate_regulator_coefficients(
            self,
            **kwargs
    ):
        self.regulator_coefficients = calculate_regulator_coefficients(
            self.putative_regulator_data,
            self.module_scores,
            **kwargs
        )
        return self

    def add_annotations(self, annotations: DataFrame, column_types: Series):
        if self.categorical_annotations is not None or self.continuous_annotations is not None:
            logging.warning('Overwriting annotation data')
        common_samples = annotations.index.intersection(self.normed_phospho.columns)
        ncommon = len(common_samples)
        if ncommon <= 1:
            raise ValueError(
                'Only %s samples in common between annotations and normed_phospho. Must be more '
                'than 1 sample in common. ' % len(ncommon)
            )
        logging.info('Annotations have %s samples in common with normed_phospho' % ncommon)
        annotations = annotations.reindex(common_samples)

        column_types = column_types.replace(annotation_column_map)
        categorical = binarize_categorical(annotations, annotations.columns[column_types == 0])

        self.categorical_annotations = categorical
        self.continuous_annotations = annotations[
            annotations.columns[column_types == 1]
        ].astype(float)
        return self

    def annotation_association(
            self,
            cat_method: Optional[str] = None,
            cont_method: Optional[str] = None,
            **mt_kwargs
    ):
        if self.categorical_annotations is None or self.continuous_annotations is None:
            raise ValueError(
                'Annotations are not defined. Provide annotation table to add_annotation method.'
            )
        cont = continuous_score_association(
            self.continuous_annotations,
            self.module_scores,
            cont_method
        )
        cat = categorical_score_association(
            self.categorical_annotations,
            self.module_scores,
            cat_method
        )
        annotation_association = pd.concat([cont, cat], join='outer', axis=1)
        self.annotation_association = annotation_association

        mt_kwargs['method'] = mt_kwargs.get('method', 'fdr_bh')
        fdr = pd.DataFrame(index=annotation_association.index)
        for col in annotation_association.columns:
            fdr.loc[:, col] = multipletests(annotation_association[col], **mt_kwargs)[1]
        self.annotation_association_FDR = fdr
        return self
