"""Infra code shared by the API and the worker.

Named `tabscribe_platform` because `platform` is a standard-library module. The transcription
pipeline must not import this package (it has no infra dependencies).
"""
