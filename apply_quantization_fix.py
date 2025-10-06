#!/usr/bin/env python3
"""
Apply the quantization fix to eliminate data loss
"""

import json
import os

def fix_quantization(new_quantization_ms=1):
    """
    Change timestamp quantization to eliminate collisions
    
    Args:
        new_quantization_ms: New quantization value (1ms recommended for 100Hz)
    """
    
    print(f"\n{'='*70}")
    print(f"APPLYING TIMESTAMP QUANTIZATION FIX")
    print(f"{'='*70}\n")
    
    print(f"Changing quantization from 10ms → {new_quantization_ms}ms")
    print(f"This will eliminate timestamp collisions and data loss\n")
    
    # Try to update config file
    config_files = ['config.json', 'app_config.json', 'web_config.json']
    
    for config_file in config_files:
        if os.path.exists(config_file):
            try:
                with open(config_file, 'r') as f:
                    config = json.load(f)
                
                # Update quantization
                if 'device' in config:
                    config['device']['timestamp_quantization_ms'] = new_quantization_ms
                    print(f"✅ Updated {config_file}: device.timestamp_quantization_ms = {new_quantization_ms}ms")
                elif 'timestamp_quantization_ms' in config:
                    config['timestamp_quantization_ms'] = new_quantization_ms
                    print(f"✅ Updated {config_file}: timestamp_quantization_ms = {new_quantization_ms}ms")
                else:
                    config['timestamp_quantization_ms'] = new_quantization_ms
                    print(f"✅ Added to {config_file}: timestamp_quantization_ms = {new_quantization_ms}ms")
                
                # Save updated config
                with open(config_file, 'w') as f:
                    json.dump(config, f, indent=2)
                
                print(f"   Saved changes to {config_file}")
                
            except Exception as e:
                print(f"⚠️  Error updating {config_file}: {e}")
    
    print(f"\n{'='*70}")
    print(f"FIX APPLIED!")
    print(f"{'='*70}\n")
    
    print(f"Next steps:")
    print(f"1. Restart your data acquisition:")
    print(f"   python3 web_server.py")
    print(f"\n2. Verify the fix:")
    print(f"   - Run for 6 minutes")
    print(f"   - Check data loss = 0%")
    print(f"\n3. Expected result:")
    print(f"   - Before: 1-10 samples lost per 36,000")
    print(f"   - After:  0 samples lost (zero data loss)")
    
    print(f"\n{'='*70}\n")


def verify_fix():
    """Verify the quantization fix was applied"""
    
    print(f"\n{'='*70}")
    print(f"VERIFYING QUANTIZATION FIX")
    print(f"{'='*70}\n")
    
    config_files = ['config.json', 'app_config.json', 'web_config.json']
    
    for config_file in config_files:
        if os.path.exists(config_file):
            try:
                with open(config_file, 'r') as f:
                    config = json.load(f)
                
                # Check quantization
                if 'device' in config and 'timestamp_quantization_ms' in config['device']:
                    q = config['device']['timestamp_quantization_ms']
                    print(f"📋 {config_file}:")
                    print(f"   timestamp_quantization_ms = {q}ms")
                    
                    if q <= 5:
                        print(f"   ✅ SAFE - No collisions at 100Hz")
                    else:
                        print(f"   ⚠️  UNSAFE - Will cause collisions at 100Hz")
                        
                elif 'timestamp_quantization_ms' in config:
                    q = config['timestamp_quantization_ms']
                    print(f"📋 {config_file}:")
                    print(f"   timestamp_quantization_ms = {q}ms")
                    
                    if q <= 5:
                        print(f"   ✅ SAFE - No collisions at 100Hz")
                    else:
                        print(f"   ⚠️  UNSAFE - Will cause collisions at 100Hz")
                        
            except Exception as e:
                print(f"⚠️  Error reading {config_file}: {e}")
    
    print(f"\n{'='*70}\n")


if __name__ == "__main__":
    import sys
    
    print("""
╔══════════════════════════════════════════════════════════════════════╗
║              TIMESTAMP QUANTIZATION FIX UTILITY                      ║
║                                                                      ║
║  Eliminates data loss caused by timestamp collisions                ║
╚══════════════════════════════════════════════════════════════════════╝
    """)
    
    if len(sys.argv) > 1:
        if sys.argv[1] == 'verify':
            verify_fix()
        else:
            try:
                q = int(sys.argv[1])
                fix_quantization(q)
            except:
                print("Usage: python3 apply_quantization_fix.py [quantization_ms | verify]")
                print("Example: python3 apply_quantization_fix.py 1")
                print("         python3 apply_quantization_fix.py verify")
    else:
        # Apply default fix (1ms)
        fix_quantization(1)
        verify_fix()

