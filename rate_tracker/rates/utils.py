"""
Utility functions for Rate-Tracker API.
"""


def format_errors(serializer_errors: dict) -> list:
    """
    Convert DRF serializer errors dict into our consistent error response format.

    Example input:  {'rate_value': ['This field is required.'], 'rate_type': ['Invalid choice.']}
    Example output: [
        {'field': 'rate_value', 'message': 'This field is required.'},
        {'field': 'rate_type', 'message': 'Invalid choice.'}
    ]
    """
    errors = []
    for field, messages in serializer_errors.items():
        for msg in messages:
            errors.append({
                'field': field if field != 'non_field_errors' else None,
                'message': str(msg),
            })
    return errors
