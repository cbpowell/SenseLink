# Copyright 2022, Charles Powell
import dpath.util
import logging


# Check if a multi-layer key exists
def keys_exist(element, *keys):
    if not isinstance(element, dict):
        raise AttributeError('keys_exists() expects dict as first argument.')
    if len(keys) == 0:
        raise AttributeError('keys_exists() expects at least two arguments, one given.')

    _element = element
    for key in keys:
        try:
            _element = _element[key]
        except KeyError:
            return False
    return True


def safekey(d, keypath, default=None):
    try:
        val = dpath.util.get(d, keypath)
        return val
    except KeyError:
        return default


def get_float_at_path(message, path, default_value=None):
    # Get attribute value, checking to force it to be a number
    raw_value = safekey(message, path)
    try:
        value = float(raw_value)
    except (ValueError, TypeError):
        logging.debug(f'Unable to convert attribute path {path} value ({raw_value}) to float, using {default_value}')
        value = default_value

    return value
