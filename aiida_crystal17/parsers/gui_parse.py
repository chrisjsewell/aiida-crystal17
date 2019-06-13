"""
This module deals with reading/creating .gui files
for use with the EXTERNAL keyword

File Format

::

    dimesionality origin_setting crystal_type energy(optional)
        a_x a_y a_z
        b_x b_y b_z
        c_x c_y c_z
    num_symm_ops (in cartesian coordinates)
        op1_rot_00 op1_rot_01 op1_rot_02
        op1_rot_10 op1_rot_11 op1_rot_12
        op1_rot_20 op1_rot_21 op1_rot_22
        op1_trans_0 op1_trans_1 op1_trans_2
        ...
    num_atoms (if cryversion<17 irreducible atoms only)
        atomic_number x y z (in cartesian coordinates)
        ...
    space_group_int_num num_symm_ops

"""
import numpy as np
import spglib

from aiida_crystal17.symmetry import (
    compute_symmetry_dataset, get_crystal_system_name, get_lattice_type_name,
    operations_frac_to_cart, convert_structure, get_hall_number_from_symmetry)

NUM_TO_CRYSTAL_TYPE_MAP = {
    1: 'triclinic',
    2: 'monoclinic',
    3: 'orthorhombic',
    4: 'tetragonal',
    5: 'hexagonal',
    6: 'cubic'
}

CRYSTAL_TYPE_TO_NUM_MAP = {
    'triclinic': 1,
    'monoclinic': 2,
    'orthorhombic': 3,
    'tetragonal': 4,
    'hexagonal': 5,
    'rhombohedral': 5,
    'triganol': 5,
    'cubic': 6
}

DIMENSIONALITY_MAP = {
    0: (False, False, False),
    1: (True, False, False),
    2: (True, True, False),
    3: (True, True, True)
}

# primitive to crystallographic, invert for other way round
# relate to: CENTRING CODE x/y, not sure what y relates to?
# see https://atztogo.github.io/spglib/definition.html#conventions-of-standardized-unit-cell
CENTERING_CODE_MAP = {
    1: [[1.0000, 0.0000, 0.0000], [0.0000, 1.0000, 0.0000],
        [0.0000, 0.0000, 1.0000]],
    2: [[1.0000, 0.0000, 0.0000], [0.0000, 1.0000, 1.0000],
        [0.0000, -1.0000, 1.0000]],  # P_A
    4: [[1.0000, 1.0000, 0.0000], [-1.0000, 1.0000, 0.0000],
        [0.0000, 0.0000, 1.0000]],  # modified P_C
    5: [[-1.0000, 1.0000, 1.0000], [1.0000, -1.0000, 1.0000],
        [1.0000, 1.0000, -1.0000]],  # P_F
    6: [[0, 1.0000, 1.0000], [1.0000, 0.0000, 1.0000],
        [1.0000, 1.0000, 0.0000]],  # P_I
}


def gui_file_read(lines):
    """read CRYSTAL geometry (.gui) file

    Parameters
    ----------
    lines: list[str]
        list of lines in the file

    Returns
    -------
    dict: structure_data
    dict: symmetry_data

    Notes
    -----
    OLDER versions of CRYSTAL are not compatible,
    because they only specify symmetrically inequivalent atomic positions
    (rather than all)

    Symmetry operations and atomic positions are assumed to be cartesian
    (rather than fractional)
    """
    symmetry = {}
    structdata = {}

    # TOP LINE
    init_data = lines[0].split()
    dimensionality = int(init_data[0])
    if dimensionality not in DIMENSIONALITY_MAP:
        raise ValueError("dimensionality was not between 0 and 3: {}".
                         format(dimensionality))
    structdata["pbc"] = DIMENSIONALITY_MAP[dimensionality]
    symmetry["centring_code"] = int(init_data[1])
    symmetry["crystal_type_code"] = int(init_data[2])
    # LATTICE SECTION
    structdata["lattice"] = [[float(num) for num in l.split()]
                             for l in lines[1:4]]
    # SYMMETRY SECTION
    nsymops = int(lines[4])
    symops = []
    for i in range(nsymops):
        symop = []
        for j in range(4):
            line_num = 5 + i * 4 + j
            values = lines[line_num].split()
            if not len(values) == 3:
                raise IOError(
                    "expected symop x, y and z coordinate on line {0}: {1}"
                    .format(line_num, lines[line_num]))
            symop.extend(
                [float(values[0]),
                    float(values[1]),
                    float(values[2])])
        symops.append(symop)
    symmetry["operations"] = symops
    symmetry["basis"] = "cartesian"
    # ATOMIC POSITIONS SECTION
    natoms = int(lines[5 + nsymops * 4])
    structdata["atomic_numbers"] = [
        int(l.split()[0])
        for l in lines[6 + nsymops * 4:6 + nsymops * 4 + natoms]]
    structdata["ccoords"] = [[
        float(num) for num in l.split()[1:4]]
        for l in lines[6 + nsymops * 4:6 + nsymops * 4 + natoms]]

    # FINAL LINE
    final_line = lines[6 + nsymops * 4 + natoms].split()
    symmetry["space_group"] = int(final_line[0])
    num_operations = int(final_line[1])
    if num_operations != nsymops:
        raise AssertionError(
            "the number of symmetry operations, "
            "specified in the operation section ({0}) and at the bottom of "
            "the file ({1}), are inconsistent".format(nsymops, num_operations))

    return structdata, symmetry


def gui_file_write(structure_data, symmetry_data=None):
    """create string of gui file content (for CRYSTAL17)

    Parameters
    ----------
    structure_data: aiida.StructureData or dict or ase.Atoms
        dict with keys: 'pbc', 'atomic_numbers', 'ccoords', 'lattice',
        or ase.Atoms, or any object that has method structure_data.get_ase()
    symmetry_data: dict or None
        keys; 'crystal_type_code', 'centring_code', 'space_group',
        'operations', 'basis'

    Returns
    -------
    lines: list[str]
        list of lines in the file

    Notes
    -----
    Older versions of CRYSTAL are not compatible,
    because they only specify symmetrically inequivalent atomic positions
    (rather than all)

    Symmetry operations and atomic positions are assumed to be cartesian
    (rather than fractional)
    """
    structure_dict = convert_structure(structure_data, "dict")

    dimensionality = sum(structure_dict["pbc"])
    atomic_numbers = structure_dict["atomic_numbers"]
    ccoords = structure_dict["ccoords"]
    lattice = structure_dict["lattice"]

    if symmetry_data is None:
        structure = convert_structure(structure_data, "aiida")
        symmetry_data = structure_to_symmetry(structure)

    if isinstance(symmetry_data, dict):
        crystal_type = symmetry_data["crystal_type_code"]
        centring_code = symmetry_data["centring_code"]
        sg_num = symmetry_data["space_group"]
        symops = symmetry_data["operations"]
        basis = symmetry_data["basis"]
    else:
        # TODO specific test for SymmetryData, and move this to separate function
        symops = symmetry_data.data.operations
        basis = symmetry_data.data.basis
        hall_number = symmetry_data.hall_number
        if hall_number is None:
            hall_number = get_hall_number_from_symmetry(symops, basis, lattice)
        crystal_type = get_crystal_type_code(hall_number)
        centring_code = get_centering_code(hall_number)
        sg_num = spglib.get_spacegroup_type(hall_number)["number"]

    if basis == "fractional":
        symops = operations_frac_to_cart(symops, lattice)
    else:
        if basis != "cartesian":
            raise AssertionError(
                "symmetry basis must be fractional or cartesian")

    # sort the symmetry operations (useful to standardize for testing)
    # symops = np.sort(symops, axis=0)

    num_symops = len(symops)
    sym_lines = []
    for symop in symops:
        sym_lines.append(symop[0:3])
        sym_lines.append(symop[3:6])
        sym_lines.append(symop[6:9])
        sym_lines.append(symop[9:12])

    # for all output numbers, we round to 9 dp and add 0, so we don't get -0.0

    geom_str_list = []
    geom_str_list.append("{0} {1} {2}".format(dimensionality, centring_code,
                                              crystal_type))
    geom_str_list.append("{0:17.9E} {1:17.9E} {2:17.9E}".format(*(
        np.round(lattice[0], 9) + 0.)))
    geom_str_list.append("{0:17.9E} {1:17.9E} {2:17.9E}".format(*(
        np.round(lattice[1], 9) + 0.)))
    geom_str_list.append("{0:17.9E} {1:17.9E} {2:17.9E}".format(*(
        np.round(lattice[2], 9) + 0.)))
    geom_str_list.append(str(num_symops))
    for sym_line in sym_lines:
        geom_str_list.append("{0:17.9E} {1:17.9E} {2:17.9E}".format(*(
            np.round(sym_line, 9) + 0.)))
    geom_str_list.append(str(len(atomic_numbers)))
    for anum, coord in zip(atomic_numbers, ccoords):
        geom_str_list.append("{0:3} {1:17.9E} {2:17.9E} {3:17.9E}".format(
            anum, *(np.round(coord, 10) + 0.)))

    geom_str_list.append("{0} {1}".format(sg_num, num_symops))
    geom_str_list.append("")

    return geom_str_list


def structure_to_symmetry(structure, symprec=1e-5, angle_tolerance=None,
                          as_cartesian=False):
    """convert a structure data object to a symmetry data dict,

    Parameters
    ----------
    structure: aiida.StructureData or dict or ase.Atoms
    symprec=1e-5: float
        Symmetry search tolerance in the unit of length.
    angle_tolerance=None: float or None
        Symmetry search tolerance in the unit of angle degrees.
        If the value is negative or None, an internally optimized routine
        is used to judge symmetry.
    as_cartesian=False: bool
        if True, convert the (fractional) symmetry operations to cartesian

    Returns
    -------
    dict
        keys; 'crystal_type_code', 'centring_code', 'space_group',
        'operations', 'basis'

    """
    structure = convert_structure(structure, "aiida")
    dataset = compute_symmetry_dataset(structure, symprec, angle_tolerance)

    space_group = dataset["number"]
    crystal_type_code = get_crystal_type_code(dataset["hall_number"])
    crystal_type_name = get_crystal_type_name(dataset["hall_number"])
    centring_code = get_centering_code(dataset["hall_number"])

    operations = []
    basis = "fractional"
    for rotation, trans in zip(dataset["rotations"], dataset["translations"]):
        operations.append(rotation.flatten().tolist() + trans.tolist())

    if as_cartesian:
        operations = operations_frac_to_cart(operations, structure.cell)
        basis = "cartesian"

    data = {
        "crystal_type_code": crystal_type_code,
        "crystal_type_name": crystal_type_name,
        "centring_code": centring_code,
        "space_group": space_group,
        "operations": operations,
        "basis": basis
    }

    return data


def get_crystal_type_code(hall_number):
    """get crystal type code, denoting the crystal system

    Parameters
    ----------
    hall_number: int

    Returns
    -------
    crystal_type_code: int

    """
    sg_number = spglib.get_spacegroup_type(hall_number)["number"]
    crystal_type = get_crystal_system_name(sg_number)
    return CRYSTAL_TYPE_TO_NUM_MAP[crystal_type]


def get_crystal_type_name(hall_number):
    """get crystal type code, denoting the crystal system

    Parameters
    ----------
    hall_number: int

    Returns
    -------
    crystal_type_name: str

    """
    sg_number = spglib.get_spacegroup_type(hall_number)["number"]
    return get_crystal_system_name(sg_number)


def get_centering_code(hall_number):
    """get crystal centering codes, to convert from primitive to conventional

    Parameters
    ----------
    hall_number: int

    Returns
    -------
    centering_code: int

    """
    sg_data = spglib.get_spacegroup_type(hall_number)
    sg_symbol = sg_data["international"]
    lattice_type = get_lattice_type_name(sg_data["number"])
    crystal_type = get_crystal_system_name(sg_data["number"])

    if "P" in sg_symbol or lattice_type == "hexagonal":
        return 1
    elif lattice_type == "rhombohedral":
        # can also be P_R (if a_length == c_length in conventional cell),
        # but crystal doesn't appear to use that anyway
        return 1
    elif "I" in sg_symbol:
        return 6
    elif "F" in sg_symbol:
        return 5
    elif "C" in sg_symbol:
        if crystal_type == "monoclinic":
            return 4
            # TODO this is P_C but don't know what code it is, maybe 3?
            # [[1.0, -1.0, 0.0], [1.0, 1.0, 0.0], [0.0, 0.0, 1.0]]
        return 4
    # elif "A" in sg_symbol:
    #     return 2
    #     TODO check this is always correct (not in original function)

    return 1
