"""
util.py

Utility functions for testing SONiC CLI
"""
import six


def parse_colon_speparated_lines(lines):
    """
    @summary: Helper function for parsing lines which consist of key-value pairs
              formatted like "<key>: <value>", where the colon can be surrounded
              by 0 or more whitespace characters
    @return: A dictionary containing key-value pairs of the output
    """
    res = {}
    for line in lines:
        fields = line.split(":")
        if len(fields) != 2:
            continue
        res[fields[0].strip()] = fields[1].strip()
    return res


def get_field_range(second_line):
    """
    @summary: Utility function to help get field range from a simple tabulate output line.
    Simple tabulate output looks like:

    Head1   Head2       H3 H4
    -----  ------  ------- --
       V1      V2       V3 V4

    @return: Returned a list of field range. E.g. [(0,4), (6, 10)] means there are two fields for
    each line, the first field is between position 0 and position 4, the second field is between
    position 6 and position 10.
    """
    field_ranges = []
    begin = 0
    while 1:
        end = second_line.find(' ', begin)
        if end == -1:
            field_ranges.append((begin, len(second_line)))
            break

        field_ranges.append((begin, end))
        begin = second_line.find('-', end)
        if begin == -1:
            break

    return field_ranges


def get_fields(line, field_ranges):
    """
    @summary: Utility function to help extract all fields from a simple tabulate output line
    based on field ranges got from function get_field_range.
    @return: A list of fields.
    """
    fields = []
    for field_range in field_ranges:
        if six.PY2:
            field = line[field_range[0]:field_range[1]].encode('utf-8')
        else:
            field = line[field_range[0]:field_range[1]]
        fields.append(field.strip())

    return fields


def get_skip_mod_list(duthost, mod_key=None):
    """
    @summary: utility function returns list of modules / peripherals absent in chassis
    by default if no keyword passed it will return all from inventory file
    provides a list under skip_modules: in inventory file for each dut
    returns a empty list if skip_modules not defined under host in inventory
    inventory example:
    DUTHOST:
    skip_modules:
        'line-cards':
          - LINE-CARD0
          - LINE-CARD2
        'fabric-cards':
          - FABRIC-CARD3
        'psus':
          - PSU4
          - PSU5
        'thermals':
          - TEMPERATURE_INFO_2
    @return a list of modules/peripherals to be skipped in check for platform test
    """

    skip_mod_list = []
    dut_vars = duthost.host.options['variable_manager'].get_vars()['hostvars'][duthost.hostname]
    if 'skip_modules' in dut_vars:
        if mod_key is None:
            for mod_type in list(dut_vars['skip_modules'].keys()):
                for mod_id in dut_vars['skip_modules'][mod_type]:
                    skip_mod_list.append(mod_id)
        else:
            for mod_type in mod_key:
                if mod_type in list(dut_vars['skip_modules'].keys()):
                    for mod_id in dut_vars['skip_modules'][mod_type]:
                        skip_mod_list.append(mod_id)
    return skip_mod_list


def get_skip_logical_module_list(duthost, mod_key=None):
    """
    @summary: utility function returns list of modules / peripherals physicsally in chassis
    But logically not part of the corresponding logical chassis
    by default if no keyword passed it will return all from inventory file
    provides a list under skip_logical_modules: in inventory file for each dut
    returns a empty list if skip_logical_modules not defined under host in inventory
    inventory example:
    DUTHOST:
    skip_logical_modules:
        'line-cards':
          - LINE-CARD0
          - LINE-CARD2

    @return a list of logical_modules/peripherals to be skipped in check for platform test
    """

    skip_logical_mod_list = []
    dut_vars = duthost.host.options['variable_manager'].get_vars()['hostvars'][duthost.hostname]
    if 'skip_logical_modules' in dut_vars:
        if mod_key is None:
            for mod_type in list(dut_vars['skip_logical_modules'].keys()):
                for mod_id in dut_vars['skip_logical_modules'][mod_type]:
                    skip_logical_mod_list.append(mod_id)
        else:
            for mod_type in mod_key:
                if mod_type in list(dut_vars['skip_logical_modules'].keys()):
                    for mod_id in dut_vars['skip_logical_modules'][mod_type]:
                        skip_logical_mod_list.append(mod_id)
    return skip_logical_mod_list


def analyze_structure(data):
    """
    Analyze the structure of a dictionary by mapping its keys to either a list of nested keys
    (for dictionary values) or the type name (for non-dictionary values).

    Args:
        data (dict): The dictionary to analyze
    Example:
        {
            "EEPROM_INFO|0x2d": {
                "expireat": 1742287244.9024103,
                "ttl": -0.001,
                "type": "hash",
                "value": {
                    "Value": "Nvidia",
                    "Name": "Vendor Name"
                }
            }
        }
    Returns:
        dict: A dictionary containing the structure analysis where:
            - For dict values: maps to a list of keys in that nested dict
            - For non-dict values: maps to the type name as a string
    """
    structure = {}
    for key, value in data.items():
        if isinstance(value, dict):
            structure[key] = list(value.keys())  # Get all keys inside the nested dictionary
        else:
            structure[key] = type(value).__name__  # Store the data type for non-dictionaries
    return structure


def get_db_keys(key_name, data):
    """
    Get all keys from a data structure that contain the specified key name.

    Args:
        key_name (str): The name to search for within the keys
        data (list): The data structure to search through

    Returns:
        list: A list of keys that contain the specified key_name
    """
    return [item for item in data if key_name in item]
