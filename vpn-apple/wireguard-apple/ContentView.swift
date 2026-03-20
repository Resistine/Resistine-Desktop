//
//  ContentView.swift
//  supavpn
//
//  Created by Shahzain Ali on 27/08/2024.
//

import SwiftUI
import NetworkExtension
struct ContentView: View {
    @State private var vpnStatusText: String = "Status: Unknown"

    var body: some View {
        VStack {
            Text(vpnStatusText)
                .padding()
            
            Button(action: {
                // Config is provided at runtime by the main app via IPC.
                // Do NOT hardcode real keys or endpoints here.
                let wgQuickConfig = """
                [Interface]
                PrivateKey = <PRIVATE_KEY>
                Address = 10.0.0.1/32
                DNS = 10.0.0.53

                [Peer]
                PublicKey = <SERVER_PUBLIC_KEY>
                AllowedIPs = 10.0.0.0/24
                Endpoint = vpn.example.com:51820
                """

                NSLog("ContentView: Requesting VPN Start via XPC")
                XPCClient.shared.startVPN(config: wgQuickConfig) { isSuccess in
                    NSLog("ContentView: VPN Start result: \(isSuccess)")
                    updateStatus()
                }
            }) {
                Text("Turn On Tunnel")
                    .padding()
                    .background(Color.green)
                    .foregroundColor(.white)
                    .cornerRadius(8)
            }

            // Button to call turnOffTunnel
            Button(action: {
                NSLog("ContentView: Requesting VPN Stop via XPC")
                XPCClient.shared.stopVPN { isSuccess in
                    NSLog("ContentView: VPN Stop result: \(isSuccess)")
                    updateStatus()
                }
            }) {
                Text("Turn Off Tunnel")
                    .padding()
                    .background(Color.red)
                    .foregroundColor(.white)
                    .cornerRadius(8)
            }
        }
        .padding()
        .onAppear {
            updateStatus()
            // Poll status every 2 seconds
            Timer.scheduledTimer(withTimeInterval: 2.0, repeats: true) { _ in
                updateStatus()
            }
        }
        .onReceive(NotificationCenter.default.publisher(for: Notification.Name("VPNStatusDidChange"))) { notification in
            if let status = notification.userInfo?["status"] as? NEVPNStatus {
                vpnStatusText = "Status: \(status)"
            } else if let isConnected = notification.userInfo?["isConnected"] as? Bool {
                vpnStatusText = isConnected ? "Status: Connected" : "Status: Disconnected"
            }
        }
    }
    
    private func updateStatus() {
        XPCClient.shared.status { status in
            DispatchQueue.main.async {
                vpnStatusText = "Status: \(status)"
            }
        }
    }
}

#Preview {
    ContentView()
}
