"""
module to read and write CRYSTAL17 .d12 files
"""
import six
from aiida_crystal17.validation import validate_dict


# TODO float format and rounding, e.g. "{}".format(0.00001) -> 1e-05, can CRYSTAL handle that?

# TODO SHRINK where IS=0 and IS1 IS2 IS3 given
# TODO FIELD/FIELDCON
# TODO FREQCALC
# TODO ANHARM
# TODO EOS

# TODO RESTART (need to provide files from previous remote folder)
# TODO fixing atoms (FRAGMENT), could do by kind but I'm not sure how this would play with using kind to reduce symmetry
# TODO initial spin based on kind


def get_keys(dct, keys, default=None, raise_error=False):
    """retrieve the leaf of a key path from a dictionary"""
    subdct = dct
    for i, key in enumerate(keys):
        if key in subdct:
            subdct = subdct[key]
        elif raise_error:
            raise ValueError("could not find key path: {}".format(
                keys[0:i + 1]))
        else:
            return default
    return subdct


def format_value(dct, keys):
    """return the value + a new line, or empty string if keys not found"""
    value = get_keys(dct, keys, None)
    if value is None:
        return ""
    if isinstance(value, dict):
        outstr = ""
        for keyword in value.keys():
            args = value[keyword]
            if isinstance(args, bool):
                if args:
                    outstr += "{}\n".format(keyword)
            elif isinstance(args, (list, tuple)):
                outstr += "{0}\n{1}\n".format(keyword,
                                              " ".join([str(a) for a in args]))
            else:
                outstr += "{0}\n{1}\n".format(keyword, args)
        return outstr

    return "{}\n".format(value)


# pylint: disable=too-many-branches
def write_input(indict, basis_sets, atom_props=None):
    """write input of a validated input dictionary

    :param indict: dictionary of input
    :param basis_sets: list of basis set strings or objects with `content` property
    :param atom_props: dictionary of atom specific properties ("spin_alpha", "spin_beta", "unfixed", "ghosts")
    :return:
    """
    # validation
    validate_dict(indict)
    if not basis_sets:
        raise ValueError("there must be at least one basis set")
    elif not (all([isinstance(b, six.string_types) for b in basis_sets])
              or all([hasattr(b, "content") for b in basis_sets])):
        raise ValueError(
            "basis_sets must be either all strings or all objects with a `content` property"
        )
    if atom_props is None:
        atom_props = {}
    if not set(atom_props.keys()).issubset(
        ["spin_alpha", "spin_beta", "unfixed", "ghosts"]):
        raise ValueError(
            "atom_props should only contain: 'spin_alpha', 'spin_beta', 'unfixed', 'ghosts'"
        )

    outstr = ""

    # Title
    title = get_keys(indict, ["title"], "CRYSTAL run")
    outstr += "{}\n".format(" ".join(title.splitlines()))  # must be one line

    # Geometry
    outstr += "EXTERNAL\n"  # we assume external geometry

    # Geometry Optional Keywords (including optimisation)
    for keyword in get_keys(indict, ["geometry", "info_print"], []):
        outstr += "{}\n".format(keyword)
    for keyword in get_keys(indict, ["geometry", "info_external"], []):
        outstr += "{}\n".format(keyword)

    if "optimise" in indict.get("geometry", {}):
        outstr += "OPTGEOM\n"
        outstr += format_value(indict, ["geometry", "optimise", "type"])
        outstr += format_value(indict, ["geometry", "optimise", "hessian"])
        outstr += format_value(indict, ["geometry", "optimise", "gradient"])
        for keyword in get_keys(indict, ["geometry", "optimise", "info_print"],
                                []):
            outstr += "{}\n".format(keyword)
        outstr += format_value(indict, ["geometry", "optimise", "convergence"])
        outstr += "END\n"

    # Geometry End
    outstr += "END\n"

    # Basis Sets
    if isinstance(basis_sets[0], six.string_types):
        outstr += "\n".join([basis_set.strip() for basis_set in basis_sets])
    else:
        outstr += "\n".join(
            [basis_set.content.strip() for basis_set in basis_sets])
    outstr += "\n99 0\n"

    # Basis Sets Optional Keywords
    outstr += format_value(indict, ["basis_set"])

    # Basis Sets End
    outstr += "END\n"

    # Hamiltonian Optional Keywords
    outstr += format_value(indict, ["scf", "single"])
    # DFT Optional Block
    if get_keys(indict, ["scf", "dft"], False):

        outstr += "DFT\n"

        xc = get_keys(indict, ["scf", "dft", "xc"], raise_error=True)
        if isinstance(xc, (tuple, list)):
            if len(xc) == 2:
                outstr += "CORRELAT\n"
                outstr += "{}\n".format(xc[0])
                outstr += "EXCHANGE\n"
                outstr += "{}\n".format(xc[1])
        else:
            outstr += format_value(indict, ["scf", "dft", "xc"])

        if get_keys(indict, ["scf", "dft", "SPIN"], False):
            outstr += "SPIN\n"

        outstr += format_value(indict, ["scf", "dft", "grid"])
        outstr += format_value(indict, ["scf", "dft", "grid_weights"])
        outstr += format_value(indict, ["scf", "dft", "numerical"])

        outstr += "END\n"

    # # K-POINTS (SHRINK\nPMN Gilat)
    outstr += "SHRINK\n"
    outstr += "{0} {1}\n".format(
        *get_keys(indict, ["scf", "k_points"], raise_error=True))

    # SCF/Other Optional Keywords
    outstr += format_value(indict, ["scf", "numerical"])
    outstr += format_value(indict, ["scf", "fock_mixing"])
    outstr += format_value(indict, ["scf", "spinlock"])
    for keyword in get_keys(indict, ["scf", "post_scf"], []):
        outstr += "{}\n".format(keyword)

    # Hamiltonian and SCF End
    outstr += "END\n"

    return outstr
