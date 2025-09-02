class NodesCreationConfig:
    """Classe per configurare un nodo del cluster"""
    def __init__(self, base_name, cpus=2, memory="2G", disk="10G", image="22.04", node_count=2):
        self.base_name = base_name
        self.cpus = cpus
        self.memory = memory
        self.disk = disk
        self.image = image
        self.node_count = node_count

class FSConfig:
    """Classe per configurare Samba sul client"""
    def __init__(self, samba_username = "sambauser", samba_password = "samba123", share_name="CephFS", mount_point="/mnt/cephfs"):
        self.samba_username = samba_username
        self.samba_password = samba_password
        self.share_name = share_name
        self.mount_point = mount_point