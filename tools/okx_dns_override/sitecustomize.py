"""Pin OKX REST DNS only for the frozen Binance-taker research subprocess."""

import socket

_ORIGINAL_GETADDRINFO = socket.getaddrinfo
_PINNED_ADDRESSES = {
    "www.okx.com": ("172.64.144.82", "104.18.43.174"),
}


def _pinned_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
    normalized = host.decode("ascii") if isinstance(host, bytes) else host
    normalized = normalized.rstrip(".").lower() if isinstance(normalized, str) else normalized
    addresses = _PINNED_ADDRESSES.get(normalized)
    if addresses is None:
        return _ORIGINAL_GETADDRINFO(host, port, family, type, proto, flags)

    resolved = []
    for address in addresses:
        resolved.extend(_ORIGINAL_GETADDRINFO(address, port, family, type, proto, flags))
    return resolved


socket.getaddrinfo = _pinned_getaddrinfo
