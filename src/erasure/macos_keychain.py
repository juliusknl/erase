"""Write existing macOS Keychain items without putting secrets in process arguments.

The legacy Keychain APIs preserve compatibility with items created by `security`.
Only a numeric OS status is exposed on failure, never input or provider output.
"""

import ctypes
import sys


class KeychainError(OSError):
    pass


def frameworks():
    if sys.platform != 'darwin':
        raise KeychainError('Keychain storage requires macOS')
    security = ctypes.CDLL('/System/Library/Frameworks/Security.framework/Security')
    core = ctypes.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
    pointer, length, text = ctypes.c_void_p, ctypes.c_uint32, ctypes.c_char_p
    security.SecKeychainFindGenericPassword.argtypes = [
        pointer, length, text, length, text, pointer, pointer, ctypes.POINTER(pointer)]
    security.SecKeychainFindGenericPassword.restype = ctypes.c_int32
    security.SecKeychainAddGenericPassword.argtypes = [
        pointer, length, text, length, text, length, pointer, ctypes.POINTER(pointer)]
    security.SecKeychainAddGenericPassword.restype = ctypes.c_int32
    security.SecKeychainItemModifyAttributesAndData.argtypes = [pointer, pointer, length, pointer]
    security.SecKeychainItemModifyAttributesAndData.restype = ctypes.c_int32
    core.CFRelease.argtypes = [pointer]
    core.CFRelease.restype = None
    return security, core


def store_secret(service: str, account: str, value: str, *, keychain=None):
    security, core = frameworks()
    service_bytes, account_bytes, value_bytes = service.encode(), account.encode(), value.encode()
    item = ctypes.c_void_p()
    try:
        status = security.SecKeychainFindGenericPassword(
            keychain, len(service_bytes), service_bytes, len(account_bytes), account_bytes,
            None, None, ctypes.byref(item))
        if status == -25300:  # errSecItemNotFound: other errors must not create/replace keys.
            status = security.SecKeychainAddGenericPassword(
                keychain, len(service_bytes), service_bytes, len(account_bytes), account_bytes,
                len(value_bytes), value_bytes, None)
        elif status == 0:
            status = security.SecKeychainItemModifyAttributesAndData(
                item, None, len(value_bytes), value_bytes)
        if status != 0:
            raise KeychainError(f'Keychain write failed (status {status}). Unlock your login Keychain and retry.')
    finally:
        if item.value:
            core.CFRelease(item)
