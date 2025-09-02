import sys
import argparse
import subprocess

from cluster_manager import ClusterManager
from hypervisor_check import print_hypervisor_status
from configs import NodesCreationConfig

def create_parser():
    """Crea il parser per gli argomenti da linea di comando"""
    parser = argparse.ArgumentParser(
        description="Gestore automatizzato per cluster Ceph con Multipass",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Esempi di utilizzo:
  %(prog)s deploy                          # Deploy interattivo con richiesta parametri
  %(prog)s deploy --nodes 5 --ram 4G       # Deploy con parametri personalizzati
  %(prog)s deploy --default                # Deploy con valori di default senza domande
        """
    )

    subparsers = parser.add_subparsers(dest='command', help='Comandi disponibili')
    
    # Comando setup
    deploy_parser = subparsers.add_parser('deploy', help='Deploy completo del cluster')
    deploy_parser.add_argument('--nodes', type=int, default=None, 
                              help='Numero di nodi del cluster (default: 3)')
    deploy_parser.add_argument('--base-name', type=str, default=None,
                              help='Nome base per i nodi (default: ceph-node)')
    deploy_parser.add_argument('--cpus', type=int, default=None,
                              help='Numero di CPU per nodo (default: 2)')
    deploy_parser.add_argument('--ram', type=str, default=None,
                              help='Quantità di RAM per nodo (default: 2G)')
    deploy_parser.add_argument('--disk', type=str, default=None,
                              help='Dimensione disco per nodo (default: 10G)')
    deploy_parser.add_argument('--os', type=str, default=None,
                              help='Sistema operativo (default: 22.04)')
    deploy_parser.add_argument('--default', action='store_true',
                              help='Usa configurazione di default senza domande')
    deploy_parser.add_argument('--with-client', action='store_true',
                              help='Crea anche una VM client alla fine del deploy')
    deploy_parser.add_argument('--debug', action='store_true',
                               help='Abilita output di debug dettagliato')

    subparsers.add_parser('destroy', help='Distrugge il cluster e le VM')

    return parser

def main():
    parser = create_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    # Verifica che Multipass sia installato e accessibile
    try:
        subprocess.run(["multipass", "version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    except FileNotFoundError:
        print("Multipass non trovato. Installarlo e assicurarsi che sia nel PATH.")
        return 1
    except subprocess.CalledProcessError:
        print("Multipass trovato ma non operativo. Verificare l'installazione.")
        return 1


    if args.command == 'deploy':
        manager = ClusterManager(is_debug=args.debug or False)
        # Controlla se un hypervisor è disponibile prima di procedere
        print("Controllo disponibilità hypervisor...")
        if not print_hypervisor_status():
            print("\n Deploy annullato: nessun hypervisor disponibile")
            print("   Configura un hypervisor e riprova.")
            return 1
        
        print()  # Riga vuota per separare dal resto dell'output
        
        # Gestione configurazione cluster
        config = None
        if args.default:
            # Usa configurazione di default
            config = manager.create_default_config()
            print("Usando configurazione di default:")
            print(f"   - Nodi: {config.node_count}")
            print(f"   - Nome base: {config.base_name}")
            print(f"   - CPU: {config.cpus}")
            print(f"   - RAM: {config.memory}")
            print(f"   - Disco: {config.disk}")
            print(f"   - OS: {config.image}")
        elif any([args.nodes, args.base_name, args.cpus, args.ram, args.disk, args.os]):
            # Usa parametri da linea di comando con default per quelli non specificati
            config = NodesCreationConfig(
                base_name=args.base_name or "ceph-node",
                cpus=args.cpus or 2,
                memory=args.ram or "2G",
                disk=args.disk or "10G",
                image=args.os or "22.04",
                node_count=args.nodes or 3
            )
            print("Usando configurazione da parametri:")
            print(f"   - Nodi: {config.node_count}")
            print(f"   - Nome base: {config.base_name}")
            print(f"   - CPU: {config.cpus}")
            print(f"   - RAM: {config.memory}")
            print(f"   - Disco: {config.disk}")
            print(f"   - OS: {config.image}")
        # Altrimenti config rimane None e setup_vms chiederà all'utente
        
        success = manager.setup_vms(config)
        if not success:
            print("Errore nel deploy del cluster")
            return 1
        
        success = manager.create_cluster()
        if not success:
            print("Errore nella configurazione del cluster")
            return 1

        success = manager.setup_osds()
        if not success:
            print("Errore nella configurazione degli OSD")
            return 1
        
        success = manager.fs_manager.setup()
        if not success:
            print("Errore nella creazione del filesystem CephFS")
            return 1

        if args.with_client:
            choice = 's'
        else:
            choice = input("Vuoi creare anche il client? [s/N]: ").strip().lower()
        
        if choice in ("s", "si", "y", "yes"):
            # Verifica che il cluster sia attivo
            cluster_info = manager.get_cluster_info()
            if not cluster_info.get("nodes"):
                print("Nessun cluster Ceph trovato. Esegui prima 'python main.py deploy'")
                return 1

            success = manager.create_client_vm()
            if not success:
                print("Errore nella creazione della VM client")
                return 1

            print("VM client deployata e configurata con successo!")
        else:
            print("Creazione del client saltata.")
        
        print("\n\n\n")
        print("Cluster deployato con successo!")
        print("   Usa 'python main.py destroy' per distruggere il cluster e le VM.")

        print("   Dati relativi al cluster:")
        primary_ip = manager.multipass.get_instance_ip(manager.PRIMARY_NODE_NAME)
        print(f"   - Nodo primario: {manager.PRIMARY_NODE_NAME} ({primary_ip})")
        print(f"   - Utente: {manager.fs_manager.samba_cfg.samba_username}")
        print(f"   - Password: {manager.fs_manager.samba_cfg.samba_password}")
        print(f"   - Punto di mount CephFS: {manager.fs_manager.samba_cfg.mount_point}")
        print(f"   - Condivisone Samba: {manager.fs_manager.samba_cfg.share_name}")
        print(f"\n   - URL accesso al fs: \\\\{primary_ip}\\{manager.fs_manager.samba_cfg.share_name}")

    elif args.command == 'destroy':
        choice = input("Questo comando pulirà tutte le VM di multipass. Sei sicuro di voler fare questo comando? [s/N]: ").strip().lower()

        if choice not in ('s', 'si', 'y', 'yes'):
            print("Comando annullato.")
            return 0

        subprocess.run(["multipass", "stop", "--all"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["multipass", "delete", "--all"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["multipass", "purge"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("Cluster distrutto temporaneamente.")

    return 0

if __name__ == '__main__':
    sys.exit(main())