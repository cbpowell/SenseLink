# Copyright 2022, Charles Powell
import dpath.util
import logging


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
