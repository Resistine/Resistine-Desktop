//
//  PacketTunnelProvider.swift
//  network-extension
//
//  Created by DhahabwhBb Jshehaha on 12/4/25.
//

import NetworkExtension
import WireGuardKit

// NOTE: This MUST be part of your network-extension target.

enum PacketTunnelProviderError: String, Error {
    case invalidProtocolConfiguration
    case cantParseWgQuickConfig
}

class PacketTunnelProvider: NEPacketTunnelProvider {
    
    private lazy var adapter: WireGuardAdapter = {
        return WireGuardAdapter(with: self) { [weak self] _, message in
            self?.log(message)
        }
    }()
    
    func log(_ message: String) {
        // Use NSLog for logging to the system console/Xcode console
        NSLog("WireGuard Tunnel: %@\n", message)
    }
    
    override func startTunnel(options: [String : NSObject]?, completionHandler: @escaping (Error?) -> Void) {
        log("ACTION [Provider Start]: Attempting to start tunnel execution.")
        
        guard let protocolConfiguration = self.protocolConfiguration as? NETunnelProviderProtocol,
              let providerConfiguration = protocolConfiguration.providerConfiguration,
              let wgQuickConfig = providerConfiguration["wgQuickConfig"] as? String else {
            log("ERROR [Provider Start]: Invalid provider configuration.")
            completionHandler(PacketTunnelProviderError.invalidProtocolConfiguration)
            return
        }
        
        // 1. Parse the configuration
        var tunnelConfiguration: TunnelConfiguration
        do {
            tunnelConfiguration = try TunnelConfiguration(fromWgQuickConfig: wgQuickConfig)
        } catch {
            log("FATAL PARSING ERROR: \(error)")
            completionHandler(error)
            return
        }
        
        // ---------------------------------------------------------
        // 👇 THE FIX: Force a valid Root DNS Search Domain
        // ---------------------------------------------------------
        // We set this to ["."] (Root). This prevents the empty string error
        // because WireGuardKit uses this value for the system Match Domains too.
        tunnelConfiguration.interface.dnsSearch = ["."]
        
        log("STATUS [DNS Fix]: Manually set dnsSearch to: \(tunnelConfiguration.interface.dnsSearch)")
        // ---------------------------------------------------------
        
        log("STATUS [Adapter Init]: Attempting to start WireGuard adapter...")
        
        adapter.start(tunnelConfiguration: tunnelConfiguration) { [weak self] adapterError in
            guard let self = self else { return }
            
            if let adapterError = adapterError {
                self.log("ERROR [Adapter Fail]: WireGuard adapter error: \(adapterError.localizedDescription)")
                self.log("ERROR [Adapter Fail]: Specific WireGuardAdapterError case: \(adapterError)")
            } else {
                let interfaceName = self.adapter.interfaceName ?? "unknown"
                self.log("SUCCESS [Adapter Start]: Tunnel interface is \(interfaceName)")
            }
            completionHandler(adapterError)
        }
    }
    
    override func stopTunnel(with reason: NEProviderStopReason, completionHandler: @escaping () -> Void) {
        log("ACTION [Provider Stop]: Stopping tunnel, reason: \(reason.rawValue)")
        adapter.stop { [weak self] error in
            guard let self = self else { return }
            if let error = error {
                self.log("ERROR [Adapter Stop]: Failed to stop WireGuard adapter: \(error.localizedDescription)")
            } else {
                self.log("STATUS [Adapter Stop]: WireGuard adapter successfully stopped.")
            }
            completionHandler()
            
#if os(macOS)
            // HACK: We kill the tunnel process ourselves due to a known macOS bug
            exit(0)
#endif
        }
    }
    
    
}
