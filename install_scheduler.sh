#!/bin/bash
# 매일 09:00 자동 실행 스케줄러 등록 스크립트
# 한 번만 실행하면 됩니다.

PLIST_PATH="$HOME/Library/LaunchAgents/com.metaauto.daily.plist"

cat > "$PLIST_PATH" << 'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.metaauto.daily</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>/Users/km/Desktop/meta-automation/generate_dashboard.py</string>
    </array>
    <key>WorkingDirectory</key>
    <string>/Users/km/Desktop/meta-automation</string>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Hour</key>
        <integer>9</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>/Users/km/Desktop/meta-automation/logs/daily.log</string>
    <key>StandardErrorPath</key>
    <string>/Users/km/Desktop/meta-automation/logs/daily_error.log</string>
    <key>RunAtLoad</key>
    <false/>
</dict>
</plist>
EOF

launchctl load "$PLIST_PATH"
echo "✅ 스케줄러 등록 완료 — 매일 09:00 자동 실행"
echo "확인: launchctl list | grep metaauto"
echo "제거: launchctl unload $PLIST_PATH"
