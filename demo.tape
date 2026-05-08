Output demo.gif
Set FontSize 16
Set Width 1000
Set Height 600
Set Theme Dracula
Set Shell "cmd.exe"
Set TypingSpeed 40ms

# Step 1: Show the config file
Type "cat examples\config.yml"
Sleep 300ms
Enter
Sleep 5s

# Step 2: Clear and start backends
Ctrl+L
Type "echo [1/4] Starting backend servers..."
Enter
Sleep 800ms
Type "start /b python -m http.server 5000 ^>nul 2^>^&1"
Enter
Sleep 1s
Type "start /b python -m http.server 5001 ^>nul 2^>^&1"
Enter
Sleep 1s

# Step 3: Start the proxy
Type "echo [2/4] Starting python-traefik proxy..."
Enter
Sleep 800ms
Type "start /b python-traefik run --config examples\config.yml ^>nul 2^>^&1"
Enter
Sleep 4s

# Step 4: Test basic routing
Type "echo [3/4] Testing HTTP routing..."
Enter
Sleep 500ms
Type "curl -s -S -H ^"Host: example.com^" http://localhost:8000/"
Enter
Sleep 2s

# Step 5: Show load balancing
Type "echo."
Type "echo --- Load balancing across backends ---"
Enter
Sleep 500ms
Type "for /l %i in (1,1,3) do @curl -s -S -H ^"Host: example.com^" http://localhost:8000/"
Enter
Sleep 3s

# Step 6: Show metrics
Type "echo [4/4] Checking Prometheus metrics..."
Enter
Sleep 500ms
Type "curl -s -S http://localhost:8000/metrics"
Enter
Sleep 5s

# Step 7: Cleanup and finish
Ctrl+L
Type "echo Demo complete! python-traefik v0.3.0"
Enter
Sleep 800ms
Type "echo Proxy running at http://localhost:8000  Dashboard at http://localhost:8080"
Enter
Sleep 2s
