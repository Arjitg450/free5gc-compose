# VDI Attack Commands

```bash
cd ~/free5gc-compose
sudo ./script/fix-vdi-network.sh
./branch-switch.sh feat/ieee-10175424
./attack_poc/run_attack.sh
```

```bash
./script/rollback-to-normal.sh
```

```bash
./attack_poc/run_attack_with_pcap.sh
```