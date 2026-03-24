//
//  WireguardkitApp.swift
//  Wireguardkit
//
//  Created by Shahzain Ali on 27/08/2024.
//

import SwiftUI
import NetworkExtension

@main
struct WireguardkitApp: App {
    
    var body: some Scene {
        WindowGroup {
            ContentView()
        }
    }
    
    init() {
        // App now uses XPCClient to talk to the XPC service
    }
}

// MARK: - Helper Extension for Logging
// Allows us to print the NEVPNStatus (inherited by NETunnelProviderSession) easily.

// MARK: - Helper Extension for Logging

// Extend the base NEVPNStatus enum, which NETunnelProviderSession.Status uses.
extension NEVPNStatus: @retroactive CustomStringConvertible {
    public var description: String {
        switch self {
        case .invalid: return "Invalid"
        case .connecting: return "Connecting"
        case .connected: return "Connected"
        case .disconnecting: return "Disconnecting"
        case .disconnected: return "Disconnected"
        case .reasserting: return "Reasserting"
        @unknown default: return "Unknown (\(self.rawValue))"
        }
    }
}
