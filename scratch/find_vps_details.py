import os
import re

history_paths = [
    "/Users/mac/.zsh_history",
    "/Users/mac/.bash_history",
    "/Users/mac/.ssh/config",
    "/Users/mac/.ssh/known_hosts",
    "/Users/mac/sinyalbingx/.env",
    "/Users/mac/active_trades.json",
    "/Users/mac/sinyalbingx/active_trades.json"
]

ip_pattern = re.compile(r'\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b')

print("--- Scanning Key Files for IP Addresses and SSH/Oracle commands ---")

for path in history_paths:
    if os.path.exists(path):
        print(f"\nFile: {path}")
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
                
                # Find IPs
                ips = ip_pattern.findall(content)
                if ips:
                    print(f"  Found IPs: {list(set(ips))}")
                
                # Find lines containing ssh, oracle, or ip
                relevant_lines = []
                for line in content.splitlines():
                    lower_line = line.lower()
                    if "ssh" in lower_line or "oracle" in lower_line or ip_pattern.search(line):
                        relevant_lines.append(line.strip())
                
                if relevant_lines:
                    print(f"  Found relevant lines ({len(relevant_lines)}):")
                    # Deduplicate and show
                    seen = set()
                    shown = 0
                    for line in relevant_lines:
                        # Normalize a bit to dedup similar lines in history
                        normalized = re.sub(r';\d+;', ';', line) # clean zsh timestamps
                        if normalized not in seen:
                            seen.add(normalized)
                            print(f"    - {line[:120]}")
                            shown += 1
                            if shown >= 25:
                                print("    - ... (truncated)")
                                break
        except Exception as e:
            print(f"  Error reading {path}: {e}")
