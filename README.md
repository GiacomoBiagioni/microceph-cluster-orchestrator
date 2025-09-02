# MicroCeph Cluster Orchestrator

Strumento per creare e gestire un cluster Ceph locale usando VM Multipass.

## Prerequisiti

- Python 3.8+
- Multipass (https://multipass.run/)
- Hypervisor:
   - Windows: Hyper-V
   - Linux: KVM/QEMU

## Installazione

1) Clona il repository
```bash
git clone https://github.com/GiacomoBiagioni/microceph-cluster-orchestrator.git
cd microceph-cluster-orchestrator
```

2) Installa Multipass (se serve)
- Windows: [Download](https://canonical.com/multipass/install)
- Ubuntu/Debian: sudo snap install multipass


## Utilizzo

- Deploy default
```bash
python main.py deploy --default
```

- Deploy personalizzato
```bash
python main.py deploy --nodes 5 --ram 4G --cpus 4 --disk 20G
```

- Deploy con client
```bash
python main.py deploy --default --with-client
```

- Deploy interattivo
```bash
python main.py deploy
```

- Distruzione cluster
```bash
python main.py destroy
```

## Parametri principali (default)

- --nodes: 2
- --base-name: ceph-node
- --cpus: 2
- --ram: 2G
- --disk: 10G
- --os: 22.04
- --with-client: false
- --debug: false

## Risultato atteso

- Accesso filesystem:
   - Samba: \\<ip-nodo-primario>\CephFS
   - Linux: mount già pronto sulla VM client (se creata)
- Credenziali Samba:
   - utente: sambauser
   - password: samba123
- Output finale: IP nodo primario, credenziali, percorso Samba, mount CephFS