import Foundation

@objc protocol VPNXPCProtocol {
    func startVPN(config: String, with reply: @escaping (Bool) -> Void)
    func stopVPN(with reply: @escaping (Bool) -> Void)
    func status(with reply: @escaping (Int) -> Void)
}
