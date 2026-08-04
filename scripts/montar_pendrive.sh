#!/bin/bash
SENHA="12345678"
echo "$SENHA" | sudo -S mount -t drvfs E: /mnt/e -o metadata,uid=1000,gid=1000,umask=022 > /tmp/mount_out.log 2>&1
rs=$?
echo "mount exit=$rs"
ls -ld /mnt/e
touch /mnt/e/.teste_write 2>> /tmp/mount_out.log && echo "ESCRITA OK" && rm /mnt/e/.teste_write || { echo "SEM PERMISSAO"; cat /tmp/mount_out.log; }