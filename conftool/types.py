import json


def choice(arg):
    args = arg.split('|')

    def is_in(x):
        if x not in args:
            raise ValueError("{} not in '{}'".format(x, " | ".join(args)))
        return x
    return is_in


def bool_validator(data):
    if not type(data) is bool:
        raise ValueError('Only boolean values are accepted.')
    return data


def dict_validator(data):
    if not isinstance(data, dict):
        raise ValueError('Field must be a dict')
    return data


def any_validator(data):
    """Any value that can be translated to json is ok."""
    try:
        json.dumps(data)
        return data
    except TypeError:
        raise ValueError('values need to be json-serializable')


validators = {
    'int': int,
    'list': lambda x: x if isinstance(x, list) else [],
    'string': str,
    'bool': bool_validator,
    'enum': choice,
    'dict': dict_validator,
    'any': any_validator,
}


class Validator(object):
    """Validator container"""

    def __init__(self, expected_type, callback):
        """This object incapsulates the expected type it is callable"""
        self.expected_type = expected_type
        self.callback = callback

    def __call__(self, arg):
        return self.callback(arg)

    def __eq__(self, other):
        return self.expected_type == other.expected_type


def get_validator(validation_string):
    """Get the validator of choice"""
    if validation_string.startswith('enum:'):
        validator, arg = validation_string.split(':', 1)
        callback = validators[validator](arg)
    else:
        validator = validation_string
        callback = validators[validation_string]
    return Validator(validator, callback)
