"""
A parser to read output from a standard CRYSTAL17 run
"""
import traceback

from aiida.common import exceptions
from aiida.engine import ExitCode
from aiida.orm import Dict
from aiida.parsers.parser import Parser

from aiida_crystal17.gulp.parsers.raw.parse_output_fit import parse_file


class GulpFittingParser(Parser):
    """
    Parser class for parsing output of a GULP potential fitting calculation
    """

    def parse(self, **kwargs):
        """
        Parse outputs, store results in database.
        """
        try:
            output_folder = self.retrieved
        except exceptions.NotExistent:
            return self.exit_codes.ERROR_NO_RETRIEVED_FOLDER

        mainout_file = self.node.get_option("output_main_file_name")
        if mainout_file not in output_folder.list_object_names():
            return self.exit_codes.ERROR_OUTPUT_FILE_MISSING

        # parse the main output file and add nodes
        self.logger.info("parsing main out file")
        with output_folder.open(mainout_file) as handle:
            try:
                result_dict, exit_code = parse_file(
                    handle, parser_class=self.__class__.__name__)
            except Exception:
                traceback.print_exc()
                return self.exit_codes.ERROR_PARSING_STDOUT

        if result_dict["parser_errors"]:
            self.logger.warning(
                "the parser raised the following errors:\n{}".format(
                    "\n\t".join(result_dict["parser_errors"])))
        if result_dict["errors"]:
            self.logger.warning(
                "the calculation raised the following errors:\n{}".format(
                    "\n\t".join(result_dict["errors"])))

        # look a stderr for fortran warnings, etc, e.g. IEEE_INVALID_FLAG IEEE_OVERFLOW_FLAG IEEE_UNDERFLOW_FLAG
        stderr_file = self.node.get_option("output_stderr_file_name")
        if stderr_file in output_folder.list_object_names():
            with output_folder.open(stderr_file) as handle:
                stderr_content = handle.read()
                if stderr_content:
                    self.logger.warning("the calculation stderr file was not empty:")
                    self.logger.warning(stderr_content)
                    result_dict["warnings"].append(stderr_content.strip())

        # TODO read dump file, to create new potential data
        # ideally would like to parse back to potential and fitting dictionaries
        # but for now extract potential lines from dump and return a SingleFileData

        self.out('results', Dict(dict=result_dict))

        if exit_code is not None:
            return self.exit_codes[exit_code]
        return ExitCode()
