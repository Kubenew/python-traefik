from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Optional

from starlette.requests import Request


@dataclass
class Rule:
    raw: str
    matcher: Callable[[Request], bool]


# ---------------------------------------------------------------------------
# Individual matchers
# ---------------------------------------------------------------------------

def _parse_single(expr: str) -> Callable[[Request], bool]:
    expr = expr.strip()

    # Host(`example.com`)
    m = re.match(r"^Host\(`([^`]+)`\)$", expr)
    if m:
        host = m.group(1).lower()
        def match(req: Request) -> bool:
            return (req.headers.get("host") or "").split(":")[0].lower() == host
        return match

    # HostRegexp(`^.*\.example\.com$`)
    m = re.match(r"^HostRegexp\(`([^`]+)`\)$", expr)
    if m:
        pattern = re.compile(m.group(1), re.IGNORECASE)
        def match(req: Request) -> bool:
            h = (req.headers.get("host") or "").split(":")[0]
            return bool(pattern.match(h))
        return match

    # PathPrefix(`/api`)
    m = re.match(r"^PathPrefix\(`([^`]+)`\)$", expr)
    if m:
        prefix = m.group(1)
        def match(req: Request) -> bool:
            return req.url.path.startswith(prefix)
        return match

    # Path(`/exact`)
    m = re.match(r"^Path\(`([^`]+)`\)$", expr)
    if m:
        path = m.group(1)
        def match(req: Request) -> bool:
            return req.url.path == path
        return match

    # Headers(`X-Custom`, `value`)
    m = re.match(r"^Headers\(`([^`]+)`,\s*`([^`]+)`\)$", expr)
    if m:
        header_name = m.group(1).lower()
        header_value = m.group(2)
        def match(req: Request) -> bool:
            return req.headers.get(header_name, "") == header_value
        return match

    # Method(`GET`)
    m = re.match(r"^Method\(`([^`]+)`\)$", expr)
    if m:
        method = m.group(1).upper()
        def match(req: Request) -> bool:
            return req.method == method
        return match

    # ClientIP(`192.168.1.0/24`) — simplified, exact match or CIDR
    m = re.match(r"^ClientIP\(`([^`]+)`\)$", expr)
    if m:
        allowed = m.group(1)
        if "/" in allowed:
            # CIDR matching
            import ipaddress
            network = ipaddress.ip_network(allowed, strict=False)
            def match(req: Request) -> bool:
                client = req.client.host if req.client else ""
                try:
                    return ipaddress.ip_address(client) in network
                except ValueError:
                    return False
            return match
        else:
            def match(req: Request) -> bool:
                return (req.client.host if req.client else "") == allowed
            return match

    raise ValueError(f"Unsupported rule expression: {expr}")


# ---------------------------------------------------------------------------
# Tokenizer for nested expressions
# ---------------------------------------------------------------------------

def _tokenize(rule: str) -> list[str]:
    """Split a rule string into tokens: matchers, &&, ||, (, )"""
    tokens: list[str] = []
    i = 0
    n = len(rule)
    while i < n:
        if rule[i] in (' ', '\t'):
            i += 1
            continue
        if rule[i] == '(' and (not tokens or tokens[-1] in ('&&', '||', '(')):
            tokens.append('(')
            i += 1
            continue
        if rule[i] == ')':
            tokens.append(')')
            i += 1
            continue
        if rule[i:i+2] == '&&':
            tokens.append('&&')
            i += 2
            continue
        if rule[i:i+2] == '||':
            tokens.append('||')
            i += 2
            continue
        # Consume a matcher expression like Host(`...`) or Headers(`...`, `...`)
        # It may contain nested parens from the function call
        j = i
        paren_depth = 0
        while j < n:
            if rule[j] == '(':
                paren_depth += 1
            elif rule[j] == ')':
                paren_depth -= 1
                if paren_depth == 0:
                    j += 1
                    break
            j += 1
        tokens.append(rule[i:j].strip())
        i = j
    return tokens


def _parse_expr(tokens: list[str], pos: int) -> tuple[Callable[[Request], bool], int]:
    """Recursive descent parser for rule expressions with && and ||."""
    left, pos = _parse_and(tokens, pos)
    while pos < len(tokens) and tokens[pos] == '||':
        pos += 1  # consume ||
        right, pos = _parse_and(tokens, pos)
        prev_left = left
        prev_right = right
        left = lambda req, _l=prev_left, _r=prev_right: _l(req) or _r(req)
    return left, pos


def _parse_and(tokens: list[str], pos: int) -> tuple[Callable[[Request], bool], int]:
    left, pos = _parse_primary(tokens, pos)
    while pos < len(tokens) and tokens[pos] == '&&':
        pos += 1  # consume &&
        right, pos = _parse_primary(tokens, pos)
        prev_left = left
        prev_right = right
        left = lambda req, _l=prev_left, _r=prev_right: _l(req) and _r(req)
    return left, pos


def _parse_primary(tokens: list[str], pos: int) -> tuple[Callable[[Request], bool], int]:
    if pos < len(tokens) and tokens[pos] == '(':
        pos += 1  # consume (
        matcher, pos = _parse_expr(tokens, pos)
        if pos < len(tokens) and tokens[pos] == ')':
            pos += 1  # consume )
        return matcher, pos
    # Must be a matcher expression
    return _parse_single(tokens[pos]), pos + 1


def parse_rule(rule: str) -> Rule:
    """Parse a Traefik-style rule string into a Rule object.

    Supports:
      - Single matchers: Host(`example.com`)
      - AND: Host(`a.com`) && PathPrefix(`/api`)
      - OR: Host(`a.com`) || Host(`b.com`)
      - Parentheses: (Host(`a.com`) || Host(`b.com`)) && PathPrefix(`/api`)
      - Matchers: Host, HostRegexp, Path, PathPrefix, Headers, Method, ClientIP
    """
    raw = rule.strip()
    tokens = _tokenize(raw)
    if not tokens:
        raise ValueError(f"Empty rule: {rule}")

    matcher, _ = _parse_expr(tokens, 0)
    return Rule(raw=raw, matcher=matcher)
