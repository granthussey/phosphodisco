from typing import Optional, List, Iterable
import sys
import logging
import argparse
import yaml
import phosphodisco


def _make_parser():
    parser = argparse.ArgumentParser(prog="phosphodisco", description="")
    parser.add_argument(
        "--version", "-v", action="version", version="%s" % phosphodisco.__version__
    )
    parser.add_argument(
        "phospho", type=str, help=''
    )
    parser.add_argument(
        "protein", type=str, help=''
    )
    parser.add_argument(
        "--output_prefix", type=str, default='phdc', help=''
    )
    parser.add_argument(
        "--min_common_values", help=''
    )
    parser.add_argument(
        "--normed_phospho", type=str, help=''
    )
    parser.add_argument(
        "--modules", type=str, help=''
    )
    parser.add_argument(
        "--putative_regulator_list", type=str, help=''
    )
    parser.add_argument(
        "--annotations", type=str, help=''
    )
    parser.add_argument(
        "--annotation_column_types", type=str, help=''
    )
    parser.add_argument(
        "--additional_kwargs_yml", type=str, help=''
    )
    return parser


def _main(args: Optional[List[str]] = None):
    if args is None:
        args = sys.argv[1:]
    args = _make_parser().parse_args(args)
    logging.info("Running phosphodisco")

    for arg in vars(args):
        logging.info("Parameter %s: %s" % (arg, getattr(args, arg)))

    output_prefix = args.output_prefix
    phospho = phosphodisco.parsers.read_phospho(args.phospho)
    protein = phosphodisco.parsers.read_protein(args.protein)
    min_common_values = args.min_common_values

    if args.normed_phospho:
        normed_phospho = phosphodisco.parsers.read_phospho(args.normed_phospho)
    else:
        normed_phospho = None

    if args.modules:
        modules = phosphodisco.parsers.read_phospho(args.modules)
    else:
        modules = None


    if args.additional_kwargs_yml:
        with open(args.additional_kwargs_yml, 'r') as fh:
            additional_kwargs_yml = yaml.load(fh, Loader=yaml.FullLoader)
    else:
        additional_kwargs_yml = {}

    data = phosphodisco.ProteomicsData(
        phospho=phospho,
        protein=protein,
        min_common_values=min_common_values,
        normed_phospho=normed_phospho,
        modules=modules,
    )
    if args.normed_phospho is None:
        data.normalize_phospho_by_protein(
            **additional_kwargs_yml.get('normalize_phospho_by_protein', {})
        )
        data.normed_phospho.to_csv('%s.normed_phospho.csv' % output_prefix)

    if args.modules is None:
        data.assign_modules(
            force_choice=True, **additional_kwargs_yml.get('assign_modules', {})
        )
        data.modules.to_csv('%s.modules.csv' % output_prefix)
    data.calculate_module_scores(
        **additional_kwargs_yml.get('calculate_module_scores', {})
    )

    if args.putative_regulator_list:
        with open(args.putative_regulator_list, 'r') as fh:
            putative_regulator_list = [gene.strip() for gene in fh.readlines()]
        data.collect_putative_regulators(
            putative_regulator_list, **additional_kwargs_yml.get('collect_putative_regulators', {})
        )
        data.calculate_regulator_coefficients(
            **additional_kwargs_yml.get('calculate_regulator_coefficients', {})
        )
        data.regulator_coefficients.to_csv('%s.putative_regulator_coefficients.csv' % output_prefix)

    if args.annotations:
        if args.annotation_column_types is None:
            logging.error(
                'Annotations were provided, but no column labels were provided. Cannot continue '
                'with annotation association calculations. '
            )
            return None
        annotations = phosphodisco.parsers.read_annotation(args.annotations)
        with open(args.annotation_column_types, 'r') as fh:
            annotation_column_types = [col.strip() for col in fh.readlines()]
        data.add_annotations(
            annotations=annotations,
            column_types=annotation_column_types
        )
        data.calculate_annotation_association(
            **additional_kwargs_yml.get('calculate_annotation_association', {})
        )
        data.annotation_association.to_csv('%s.annotation_association.csv' % output_prefix)


if __name__ == "__main__":
    _main()
