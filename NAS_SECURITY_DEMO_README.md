# NAS Security Demonstration Guide

This guide provides step-by-step instructions to demonstrate NAS (Non-Access Stratum) security in Free5GC 5G core network.

## Prerequisites

- Ubuntu/Linux system with Docker and Docker Compose installed
- At least 8GB RAM and 4 CPU cores
- Internet connectivity
- Git installed

## Step 1: Environment Setup

### 1.1 Clone Free5GC Compose Repository
```bash
cd /home/arjit/ISEA
git clone https://github.com/free5gc/free5gc-compose.git
cd free5gc-compose
```

### 1.2 Install GTP5G Kernel Module
```bash
cd /home/arjit/ISEA
git clone -b v0.9.5 https://github.com/free5gc/gtp5g.git
cd gtp5g
make clean && make
sudo make install
sudo modprobe gtp5g
```

### 1.3 Verify GTP5G Installation
```bash
lsmod | grep gtp5g
# Should show: gtp5g module loaded
```

## Step 2: Deploy Free5GC Core Network

### 2.1 Start All Services
```bash
cd /home/arjit/ISEA/free5gc-compose
docker-compose up -d
```

### 2.2 Verify All Containers Are Running
```bash
docker ps
# Should show 17 containers all in "Up" status
```

### 2.3 Check Core Network Functions
```bash
# Check AMF (Access and Mobility Management Function)
docker logs amf --tail 10

# Check AUSF (Authentication Server Function)
docker logs ausf --tail 10

# Check UPF (User Plane Function)
docker logs upf --tail 10
```

### 2.4 Verify Network Connectivity
```bash
# Check if Free5GC network is created
docker network ls | grep free5gc
```

## Step 3: NAS Security Configuration Analysis

### 3.1 Examine UE Security Configuration
```bash
cd /home/arjit/ISEA/free5gc-compose
docker exec ueransim cat /ueransim/config/uecfg.yaml
```

**Key NAS Security Parameters to Note:**
- `key`: Permanent subscription key for authentication
- `op`/`opc`: Operator code for key derivation
- `integrity`: Supported integrity algorithms (IA1, IA2, IA3)
- `ciphering`: Supported encryption algorithms (EA1, EA2, EA3)

### 3.2 Examine gNodeB Configuration
```bash
docker exec ueransim cat /ueransim/config/gnbcfg.yaml
```

## Step 4: Capture NAS Security Traffic

### 4.1 Create Capture Directory
```bash
cd /home/arjit/ISEA/free5gc-compose
mkdir -p captures
```

### 4.2 Start Packet Capture (Optional - for Advanced Analysis)
```bash
# Start tcpdump to capture NGAP traffic carrying NAS messages
sudo tcpdump -i any -w captures/nas_security_demo.pcap host 10.100.200.16 or host 10.100.200.14 &
```

## Step 5: Demonstrate NAS Security

### 5.1 Stop Any Previous UE Simulation
```bash
docker exec ueransim pkill nr-ue 2>/dev/null || true
```

### 5.2 Start UE Registration (This Triggers NAS Security)
```bash
cd /home/arjit/ISEA/free5gc-compose
timeout 30 docker exec ueransim ./nr-ue -c ./config/uecfg.yaml
```

**Expected Output Showing NAS Security Working:**
```
[nas] [debug] Authentication Request received
[nas] [debug] Received SQN [xxxxxxxxxxxxxxx]
[nas] [debug] Security Mode Command received
[nas] [debug] Selected integrity[2] ciphering[0]
[nas] [info] UE switches to state [MM-REGISTERED/NORMAL-SERVICE]
[nas] [info] Initial Registration is successful
```

### 5.3 Verify Secure Network Interfaces Created
```bash
docker exec ueransim ip addr show | grep -A 3 uesimtun
```

**Expected Output:**
```
uesimtun0: <POINTOPOINT,PROMISC,NOTRAILERS,UP,LOWER_UP> mtu 1400
    inet 10.60.0.X/16 scope global uesimtun0
uesimtun1: <POINTOPOINT,PROMISC,NOTRAILERS,UP,LOWER_UP> mtu 1400
    inet 10.61.0.X/16 scope global uesimtun1
```

### 5.4 Test Connectivity Through Secure 5G Network
```bash
docker exec ueransim ping -c 3 google.com
```

**Expected Output:**
```
PING google.com (xxx.xxx.xxx.xxx) 56(84) bytes of data.
64 bytes from xxx: icmp_seq=1 ttl=xxx time=xx.x ms
64 bytes from xxx: icmp_seq=2 ttl=xxx time=xx.x ms
64 bytes from xxx: icmp_seq=3 ttl=xxx time=xx.x ms

--- google.com ping statistics ---
3 packets transmitted, 3 received, 0% packet loss
```

## Step 6: Verify NAS Security from Network Side

### 6.1 Check AUSF Authentication Logs
```bash
docker logs ausf --tail 20 | grep -i "auth\|key"
```

**Expected Output:**
```
[AUSF][UeAuth] Use 5G AKA auth method
[AUSF][5gAka] XresStar = [authentication response]
[AUSF][5gAka] 5G AKA confirmation succeeded
```

### 6.2 Check AMF NAS Handling Logs
```bash
docker logs amf --tail 30 | grep -i "nas\|security\|auth"
```

### 6.3 Verify UE Registration Status
```bash
# Check if UE is registered in AMF
docker logs amf --tail 10 | grep "MM-REGISTERED"
```

## Step 7: Advanced Security Analysis (Optional)

### 7.1 Stop Packet Capture
```bash
sudo pkill tcpdump
```

### 7.2 Analyze Captured Traffic
```bash
cd /home/arjit/ISEA/free5gc-compose
tshark -r captures/nas_security_demo.pcap -c 20
```

### 7.3 Check for Multiple UE Registrations
```bash
# Register another UE to see security procedures repeat
timeout 20 docker exec ueransim ./nr-ue -c ./config/uecfg.yaml
```

## Step 8: Cleanup and Reset

### 8.1 Stop UE Simulation
```bash
docker exec ueransim pkill nr-ue 2>/dev/null || true
```

### 8.2 Stop All Services (if needed)
```bash
cd /home/arjit/ISEA/free5gc-compose
docker-compose down
```

### 8.3 Remove GTP5G Module (if needed)
```bash
sudo rmmod gtp5g
```

## Understanding the NAS Security Flow

### Authentication (5G-AKA)
1. **UE → AMF**: Registration Request (unprotected)
2. **AMF → AUSF**: Authentication Request
3. **AUSF → UE**: Authentication Challenge (RAND, AUTN)
4. **UE → AUSF**: Authentication Response (RES)
5. **AUSF**: Verify RES, generate keys

### Security Mode Command
1. **AMF → UE**: Security Mode Command (algorithm selection)
2. **UE**: Derive NAS keys, verify algorithms
3. **UE → AMF**: Security Mode Complete (integrity protected)

### Protected Communication
- All subsequent NAS messages are integrity protected
- Selected algorithms: typically 128-NIA2 (AES) for integrity
- Key hierarchy: K → CK,IK → Kausf → Kseaf → Kamf → Knas_int

## Security Algorithms Demonstrated

### Integrity Algorithms
- **IA1 (128-NIA1)**: SNOW 3G based
- **IA2 (128-NIA2)**: AES based (typically selected)
- **IA3 (128-NIA3)**: ZUC based

### Encryption Algorithms
- **EA1 (128-NEA1)**: SNOW 3G based
- **EA2 (128-NEA2)**: AES based
- **EA3 (128-NEA3)**: ZUC based
- **EA0 (NEA0)**: No encryption (often selected for control plane)

## Troubleshooting

### Common Issues and Solutions

1. **GTP5G Module Not Found**
   ```bash
   # Rebuild and install GTP5G
   cd /home/arjit/ISEA/gtp5g
   make clean && make && sudo make install
   sudo modprobe gtp5g
   ```

2. **Containers Not Starting**
   ```bash
   # Check Docker daemon and restart
   sudo systemctl status docker
   docker-compose down && docker-compose up -d
   ```

3. **UE Registration Fails**
   ```bash
   # Check AMF logs for errors
   docker logs amf --tail 50
   # Check if subscriber exists in UDR
   docker logs udr --tail 20
   ```

4. **No Network Connectivity**
   ```bash
   # Verify UPF is running and GTP5G is loaded
   docker logs upf --tail 10
   lsmod | grep gtp5g
   ```

## Success Indicators

✅ **NAS Security is Working When You See:**
- Authentication Request/Response exchange
- Security Mode Command with algorithm selection
- UE state transition to MM-REGISTERED/NORMAL-SERVICE
- Successful PDU session establishment
- Working internet connectivity through uesimtun interfaces
- AUSF logs showing "5G AKA confirmation succeeded"

## Files Generated

After running this demonstration, you'll have:
- `captures/nas_security_demo.pcap` - Network traffic capture
- Container logs showing NAS security procedures
- Working UE tunnels with internet connectivity

This demonstrates a complete, working 5G NAS security implementation using Free5GC's production-grade code.