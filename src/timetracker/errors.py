# errors.py
#
# Author: Patrick Beal
#
# Exceptions shared across the app


class TimeTrackerError(Exception):
    """
    An error caused by the user's input rather than a bug, such as an unknown
    client name. The CLI prints these as a plain message instead of a traceback.
    """
