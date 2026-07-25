import ipaddress

from fastapi import Request


def get_client_ip(request: Request) -> str:
    # Uvicorn rewrites request.client only for proxies explicitly trusted by its
    # forwarded-allow-ips setting. Reading X-Forwarded-For here would let direct
    # clients spoof an allowed address.
    return request.client.host if request.client else ""


def check_ip_allowed(allowed_ips: list[str], client_ip: str) -> bool:
    if not allowed_ips:
        return True
    try:
        addr = ipaddress.ip_address(client_ip)
    except ValueError:
        return False
    for entry in allowed_ips:
        try:
            network = ipaddress.ip_network(entry, strict=False)
            if addr in network:
                return True
        except ValueError:
            continue
    return False
