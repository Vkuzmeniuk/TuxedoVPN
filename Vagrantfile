cluster = {
  'vpn-srv-01' => {
    hostname: 'vpn-srv-01', :ip_int => '192.168.56.103', :ip_vb => '10.0.2.16'
  },
  'vpn-srv-02' => {
    hostname: 'vpn-srv-02', :ip_int => '192.168.56.106', :ip_vb => '10.0.2.17'
  },
  'mgmt-srv-01' => {
    hostname: 'mgmt-srv-01', :ip_int => '192.168.56.102', :ip_vb => '10.0.2.18'
  }
}

DNS_SERVER_IP = '192.168.100.1'

Vagrant.configure("2") do |config|
  # Global configuration for all VMs
  config.vm.provider "virtualbox" do |vb|
    vb.memory = "4096" # RAM
    vb.cpus = 2 # CPU cores
    vb.gui = true # Show GUI on boot
  end

  # Ruby's each_with_index
  # cluster (Hash) contains node definitions
  # |(node,info),index| =>
  # index is the iteration index (like "i" in "for i in (0..10); do; done")
  # (node,info): node is the key in `cluster`, info is the node data
  # example: element with index 2 has:
  # - node == 'vpn-srv-02'
  # - info == {...} (data for that node)
  cluster.each_with_index do |(node,info),index|
    config.vm.define node do |cfg|
      cfg.vm.box = "ubuntu/jammy64" # Base box image
      cfg.vm.box_version = "20241002.0.0" # Box version
      cfg.vm.hostname = info[:hostname] # VM hostname
      cfg.vm.network "private_network", ip: info[:ip_int] # VM IP for the VirtualBox host-only adapter
      #cfg.vm.network "private_network" # VM IP for NatNetwork

      # Add NatNetwork as nic3
      cfg.vm.provider "virtualbox" do |vbmachine|
        # vboxmanage modifyvm vagrant-conf_vpn-srv-02_1761821149427_47343 --nic1 NatNetwork
        vbmachine.customize ["modifyvm", :id, "--nic3", "NatNetwork", "--nat-network3", "NatNetwork"]

        # VBoxManage modifyvm <uuid | vmname> --name=vpn-srv-02
        vbmachine.customize ["modifyvm", :id, "--name", info[:hostname]]
      end
      
	      cfg.vm.provision "shell" do |shell|
	        shell.env = {
	          IP_ADDR: info[:ip_vb],
	          LOC_DNS_SERVER_IP: DNS_SERVER_IP,
	          SUPPORT_PASSWORD: ENV["TUXEDOVPN_VAGRANT_SUPPORT_PASSWORD"].to_s
	        }
	        shell.inline = <<-SHELL
	          echo "CREATE SUPPORT USER"
	          sudo useradd support -m -s /bin/bash
          echo "ADD SUPPORT USER TO SUDO GROUP"
          sudo usermod -a -G sudo support
          id support
          echo "MAKE SUDO TO BE EXECUTABLE WITHOUT PASSWORD"
          sudo touch /etc/sudoers.d/support
          echo "support ALL=(ALL:ALL) NOPASSWD:ALL" | sudo tee /etc/sudoers.d/support
          sudo chmod 440 /etc/sudoers.d/support
	          if [[ -n "${SUPPORT_PASSWORD:-}" ]]; then
	            echo "SETUP SUPPORT PASSWORD FROM ENV"
	            echo "support:${SUPPORT_PASSWORD}" | sudo chpasswd
	          else
	            echo "NO SUPPORT PASSWORD PROVIDED (LOCK ACCOUNT PASSWORD)"
	            sudo passwd -l support || true
	          fi
	          echo "UPDATE PACKETS"
	          sudo apt update -y || true
	          sudo apt upgrade -y
          echo "FOR DEPLOYMENT: ALLOW IMAGE BROUGHT FROM VAGRANT BOX TO ACCEPT OTHER SSH CONNECTIONS"
          sudo sed -i "s/no/yes/" /etc/ssh/sshd_config.d/60-cloudimg-settings.conf || true
          sudo systemctl restart sshd || true

          # (?) add config for the 3rd interface (NatNetwork)
          echo "install network tools"
          sudo apt install -y net-tools

          echo "    enp0s9:" | sudo tee -a /etc/netplan/50-vagrant.yaml
          echo "      dhcp4: false" | sudo tee -a /etc/netplan/50-vagrant.yaml
          echo "      dhcp6: false" | sudo tee -a /etc/netplan/50-vagrant.yaml
          echo "      addresses: " | sudo tee -a /etc/netplan/50-vagrant.yaml
          echo "      - $IP_ADDR/24" | sudo tee -a /etc/netplan/50-vagrant.yaml
          echo "      nameservers:" | sudo tee -a /etc/netplan/50-vagrant.yaml
          echo "        addresses: [${LOC_DNS_SERVER_IP}]" | sudo tee -a /etc/netplan/50-vagrant.yaml
          echo "      routes:" | sudo tee -a /etc/netplan/50-vagrant.yaml
          echo "        - to: default" | sudo tee -a /etc/netplan/50-vagrant.yaml
          echo "          via: 10.0.2.1" | sudo tee -a /etc/netplan/50-vagrant.yaml

          sudo cat /etc/netplan/50-vagrant.yaml

          echo "activate new interface"
          sudo netplan apply

          if [[ $(hostname) == "mgmt-srv-01" ]]
          then
            echo "INSTALL COMMON PACKETS"
            sudo apt install -y software-properties-common || true
            echo "ADD ANSIBLE REPO"
            sudo add-apt-repository --yes --update ppa:ansible/ansible || true
            echo "INSTALL ANSIBLE"
            sudo apt install -y ansible || true
            echo "CREATE PRIVATE SSH KEY WITH EMPTY PASSPHRASE - JUST IN CASE IF REQUIRED IN PARALLEL WITH ANSIBLE"
            sudo -u support mkdir /home/support/.ssh || true
            sudo -u support chmod 700 /home/support/.ssh || true
            yes | sudo -u support ssh-keygen -f /home/support/.ssh/id_rsa -t rsa -N "" || true
          fi

          echo "SETUP COMPLETE, SHUTDOWN"
          sudo shutdown -r now
        SHELL
      end
    end
  end
end
