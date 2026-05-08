"""Generate a demo GIF for python-traefik."""

from PIL import Image, ImageDraw, ImageFont
import os
import warnings

warnings.filterwarnings("ignore", category=SyntaxWarning)

FONT_SIZE = 16
LINE_HEIGHT = 21
MARGIN = 14
COLS = 65
ROWS = 26
WIDTH = MARGIN * 2 + COLS * 9
HEIGHT = MARGIN * 2 + ROWS * LINE_HEIGHT
BG = "#1e1e2e"
FG = "#cdd6f4"
GREEN = "#a6e3a1"
CYAN = "#89b4fa"
YELLOW = "#f9e2af"
PROMPT = "$ "


def load_font():
    for name in ["Consolas", "cour", "Courier New", "DejaVuSansMono"]:
        try:
            return ImageFont.truetype(name, FONT_SIZE)
        except OSError:
            continue
    return ImageFont.load_default()


font = load_font()


def tw(text):
    """Text width in pixels."""
    return font.getlength(text)


def make_frame(lines):
    img = Image.new("RGB", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(img)
    y = MARGIN
    for item in lines:
        if isinstance(item, str):
            text, color = item, FG
        elif item is None:
            y += LINE_HEIGHT
            continue
        else:
            text, color = item
        draw.text((MARGIN, y), text, font=font, fill=color)
        y += LINE_HEIGHT
    return img


def typing_frames(cmd, prefix, output, hold=15):
    """Produce frames: typing animation, then output lines scrolling in."""
    frames = []
    full_before = prefix + [(PROMPT + cmd, FG)]

    # typing
    for i in range(1, len(cmd) + 1):
        lines = prefix + [(PROMPT + cmd[:i], FG)]
        img = Image.new("RGB", (WIDTH, HEIGHT), BG)
        draw = ImageDraw.Draw(img)
        y = MARGIN
        for item in prefix:
            t, c = item if isinstance(item, tuple) else (item, FG)
            draw.text((MARGIN, y), t, font=font, fill=c)
            y += LINE_HEIGHT
        typed = PROMPT + cmd[:i]
        draw.text((MARGIN, y), typed, font=font, fill=FG)
        cx = MARGIN + tw(typed)
        cy = y
        draw.rectangle([cx, cy, cx + tw(cmd[i - 1]) if i <= len(cmd) else cx + 6, cy + FONT_SIZE], fill="#585b70")
        draw.text((cx, cy), cmd[i - 1], font=font, fill=BG)
        frames.append(img)

    # brief pause before output
    for _ in range(6):
        frames.append(make_frame(full_before))

    # output scroll in
    shown = full_before[:]
    for line in output:
        shown.append(line)
        for _ in range(2):
            frames.append(make_frame(shown))

    # hold final
    for _ in range(hold):
        frames.append(make_frame(shown))
    return frames, shown


def main():
    print("Generating demo GIF...")
    all_frames = []
    state = []

    # Header
    header = ("# python-traefik -- Demo", GREEN)
    blank = ("", None)

    # Step 1: Show config
    print("  Step 1/6: Config...")
    config = [
        header,
        blank,
        ("  entryPoints:", FG),
        ('    web:  address: ":8000"    protocol: http', FG),
        ('    web-secure:  address: ":8443"    protocol: https', FG),
        blank,
        ("  routers:", FG),
        ('    api_router:  rule: "Host(`api.example.com`) && PathPrefix(`/v1`)"', FG),
        ('    web_router:  rule: "Host(`example.com`) && PathPrefix(`/`)"', FG),
        blank,
        ("  services:", FG),
        ('    api_service:  servers: [localhost:5000, localhost:5001]', FG),
        ('    web_service:  servers: [localhost:8080]', FG),
        blank,
        ("  metrics:  enabled: true   path: /metrics", FG),
        ("  healthcheck:  enabled: true   interval: 5s", FG),
    ]
    f, state = typing_frames("cat examples/config.yml", state, config, hold=20)
    all_frames.extend(f)

    # Step 2: Start backends
    print("  Step 2/6: Starting backends...")
    state.append(blank)
    state.append(("", None))
    state.append(("# Starting backend servers...", GREEN))
    text1 = ("  [Backend 1] HTTP :5000", CYAN)
    f, state = typing_frames(
        'start /b python -m http.server 5000 >nul 2>&1',
        state, [text1], hold=8,
    )
    all_frames.extend(f)

    state.append(blank)
    text2 = ("  [Backend 2] HTTP :5001", CYAN)
    f, state = typing_frames(
        'start /b python -m http.server 5001 >nul 2>&1',
        state, [text2], hold=8,
    )
    all_frames.extend(f)

    # Step 3: Start proxy
    print("  Step 3/6: Starting proxy...")
    state.append(blank)
    state.append(("# Starting python-traefik proxy...", GREEN))
    proxy_out = [
        ("  [proxy] Listening on :8000", CYAN),
        ("  [proxy] Dashboard at :8080/dashboard", CYAN),
        ("  [proxy] Metrics at /metrics", CYAN),
    ]
    f, state = typing_frames(
        'python-traefik run --config examples/config.yml',
        state, proxy_out, hold=15,
    )
    all_frames.extend(f)

    # Step 4: Curl request
    print("  Step 4/6: HTTP routing...")
    state.append(blank)
    state.append(("# Testing HTTP routing...", GREEN))
    curl_out = [
        ('  HTTP/1.0 200 OK', FG),
        ('  Server: SimpleHTTP/', FG),
        ('  <!DOCTYPE html>...', FG),
        ('', None),
        ('  [Routed to Backend 1 :5000]', CYAN),
    ]
    f, state = typing_frames(
        'curl -s -H "Host: example.com" http://localhost:8000/',
        state, curl_out, hold=12,
    )
    all_frames.extend(f)

    # Step 5: Load balancing
    print("  Step 5/6: Load balancing...")
    state.append(blank)
    state.append(("# Load balancing (3 requests)...", GREEN))
    bal_out = [
        ('  Request 1 -> Backend 1 (port 5000)', FG),
        ('  Request 2 -> Backend 2 (port 5001)', FG),
        ('  Request 3 -> Backend 1 (port 5000)', FG),
    ]
    f, state = typing_frames(
        'for /l %i in (1,1,3) do curl -s -H "Host: example.com" http://localhost:8000/',
        state, bal_out, hold=12,
    )
    all_frames.extend(f)

    # Step 6: Metrics
    print("  Step 6/6: Metrics...")
    state.append(blank)
    state.append(("# Prometheus metrics...", GREEN))
    metrics = [
        ('  # HELP python_traefik_requests_total Total HTTP requests', FG),
        ('  # TYPE python_traefik_requests_total counter', FG),
        ('  python_traefik_requests_total{router="web_router",'
         'service="web_service",method="GET",status="200"} 4', FG),
        ('  python_traefik_requests_total{router="api_router",'
         'service="api_service",method="GET",status="200"} 2', FG),
        ('', None),
        ('  # HELP python_traefik_request_latency_seconds', FG),
        ('  # TYPE python_traefik_request_latency_seconds histogram', FG),
        ('  python_traefik_request_latency_seconds_count{'
         'router="web_router",service="web_service"} 4', FG),
    ]
    f, state = typing_frames(
        'curl -s http://localhost:8000/metrics',
        state, metrics, hold=25,
    )
    all_frames.extend(f)

    # Final screen
    print("  Final frame...")
    fin = [
        ("", None),
        ("# python-traefik v0.3.0 -- Demo Complete!", GREEN),
        ("", None),
        ("  Proxy      : http://localhost:8000", CYAN),
        ("  Dashboard  : http://localhost:8080/dashboard", CYAN),
        ("  Metrics    : http://localhost:8000/metrics", CYAN),
        ("  Config     : examples/config.yml", CYAN),
        ("", None),
        ("  Install    : pip install python-traefik", YELLOW),
        ("  GitHub     : https://github.com/Kubenew/python-traefik", YELLOW),
    ]
    for _ in range(40):
        all_frames.append(make_frame(fin))

    print(f"  Total frames: {len(all_frames)}")

    path = "demo.gif"
    all_frames[0].save(
        path,
        save_all=True,
        append_images=all_frames[1:],
        duration=70,
        loop=0,
        optimize=False,
    )
    print(f"Demo GIF saved: {path}")


if __name__ == "__main__":
    main()
