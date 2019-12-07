import pandas as pd
import numpy as np
from pandas import DataFrame
import logging
from typing import Optional, Iterable
from .classes import ProteomicsData


def read_protein(file_path: str) -> Optional[DataFrame]:
    if file_path[-4:] = '.tsv':
        sep = '\t'

    elif file_path[-4:] = '.csv':
        sep=','

    else:
        logging.ERROR('Input file is not a .csv or .tsv')
        return None

    return pd.read_csv(file_path, sep=sep, index_col=0).replace(
        ['na', 'NA', 'NAN', 'nan', 'NaN', 'Na'], np.nan
    ).astype(float)


def read_phospho(file_path: str) -> Optional[DataFrame]:
    if file_path[-4:] = '.tsv':
        sep = '\t'

    elif file_path[-4:] = '.csv':
        sep = ','

    else:
        logging.ERROR('Input file is not a .csv or .tsv')
        return None

    return pd.read_csv(file_path, sep=sep, index_col=[0,1]).replace(
        ['na', 'NA', 'NAN', 'nan', 'NaN', 'Na'], np.nan
    ).astype(float)


def column_normalize(df: DataFrame, method: str) -> Optional[DataFrame]:
    """
    Provides several
    Args:
        df:
        method:

    Returns:

    """
    if method == "median_of_ratios":
        return df.divide(df.divide(df.mean(axis=1), axis=0).median())

    if method == "median"":
        return df.divide(df.median())

    if method == 'upper_quartile":
        return df.divide(np.nanquantile(df, 0.75))

    if method == "twocomp_median":
        pass

    logging.ERROR(
        'Passed method not valid. Must be one of: median_of_ratios, median, upper_quartile, '
        'twocomp_median.'
    )
    return None


def prepare_phospho(
        ph_file: str,
        prot_file: str,
        normalize_method: Optional[str] = None,
        min_common_values: int = 5,
        ridge_cv_alphas: Optional[Iterable] = None
) -> ProteomicsData:

    phospho = read_phospho(ph_file)
    protein = read_protein(prot_file)
    if normalize_method:
        phospho = column_normalize(phospho, normalize_method)
        protein = column_normalize(protein, normalize_method)

    data = ProteomicsData(phospho, protein, min_common_values)
    data.normalize_phospho_by_protein(ridge_cv_alphas)

    return data


