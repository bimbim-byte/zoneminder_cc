@echo off
setlocal
set SECRET=...Change me to something unique...
set PWHASH=$2y$10$c76lvRgmjJeS6Us4Ddi2L.G2f0s7JlKBGiYDJMFglSROjPbGjtfb2
set TARGET=281576c3e7bb2458f3c48a623b2b4b1f
docker cp scripts/_verify_login.py camera-dashboard:/tmp/v.py >nul
docker exec -e "T_SECRET=%SECRET%" -e "T_PWHASH=%PWHASH%" -e "T_TARGET=%TARGET%" -e "T_USER=admin" camera-dashboard python /tmp/v.py calc
