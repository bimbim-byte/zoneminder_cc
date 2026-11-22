#!/bin/sh
# Mencetak seluruh monitor (termasuk yang soft-delete) dari database ZoneMinder.
set -e
PW=$(cat /run/secrets/zm_db_pass)
mariadb -uzmuser -p"$PW" zm -e \
  "SELECT Id,Name,Deleted,Function,Capturing,Analysing,Recording FROM Monitors ORDER BY Id;"
