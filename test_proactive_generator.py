#!/usr/bin/env python3
"""
Test the proactive wraparound detection in the real system
"""

import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from timing_fix import SimplifiedTimestampGenerator
import time

def test_proactive_wraparound_detection():
    """Test the proactive wraparound detection in the generator"""
    print("🧪 Testing Proactive Wraparound Detection in Generator")
    print("=" * 60)
    
    # Create generator
    generator = SimplifiedTimestampGenerator(expected_rate=100.0, quantization_ms=1)
    
    # Simulate the exact sequence progression that happens in the real system
    test_sequences = [65530, 65531, 65532, 65533, 65534, 65535, 0, 1, 2, 3, 4, 5]
    
    print(f"📋 Testing sequence progression: {test_sequences}")
    
    for i, seq in enumerate(test_sequences):
        print(f"\n--- Processing sequence {seq} ---")
        
        # Generate timestamp (this should trigger proactive detection)
        timestamp = generator.generate_timestamp(seq)
        
        # Show internal state
        print(f"   Generated timestamp: {timestamp}ms")
        print(f"   Reference sequence: {generator.reference_sequence}")
        print(f"   Last sequence: {generator.last_sequence}")
        
        # Check stats
        stats = generator.get_stats()
        print(f"   Wraparounds detected: {stats['wraparounds_detected']}")
        print(f"   Max sequence seen: {stats['max_sequence_seen']}")
        
        # Check if we're getting reasonable timestamps
        if i > 0:
            prev_seq = test_sequences[i-1]
            if seq == 0 and prev_seq == 65535:
                # This is the critical wraparound point
                print(f"   🚨 CRITICAL: Wraparound point reached!")
                print(f"   Previous: {prev_seq}, Current: {seq}")
                # Calculate actual timestamp jump
                prev_timestamp = generator.get_stats()['last_timestamp']
                if prev_timestamp:
                    actual_jump = timestamp - (prev_timestamp * 1000)
                    print(f"   Timestamp jump: {actual_jump:.1f}ms")
                else:
                    print(f"   Timestamp jump: N/A")
    
    # Show final stats
    stats = generator.get_stats()
    print(f"\n📊 Final Stats:")
    print(f"   Wraparounds detected: {stats['wraparounds_detected']}")
    print(f"   Sequence resets: {stats['sequence_resets']}")
    print(f"   Max sequence seen: {stats['max_sequence_seen']}")
    print(f"   Samples processed: {stats['samples_processed']}")

if __name__ == "__main__":
    test_proactive_wraparound_detection()
    print("\n✅ Proactive wraparound detection test completed!")
