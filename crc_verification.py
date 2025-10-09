#!/usr/bin/env python3
"""
CRC/Checksum Verification for Binary Frames
Supports CRC-16, CRC-32, and simple checksums
"""

import struct
import logging
from typing import Optional, Tuple, Union
from enum import Enum

def crc16_xmodem(data: bytes) -> int:
    """Simple CRC-16 XMODEM implementation"""
    crc = 0x0000
    for byte in data:
        crc ^= byte << 8
        for _ in range(8):
            if crc & 0x8000:
                crc = (crc << 1) ^ 0x1021
            else:
                crc <<= 1
            crc &= 0xFFFF
    return crc

logger = logging.getLogger(__name__)

class CRCType(Enum):
    """Supported CRC types"""
    CRC16_CCITT = "crc16_ccitt"
    CRC16_MODBUS = "crc16_modbus"
    CRC16_XMODEM = "crc16_xmodem"
    CRC32 = "crc32"
    SIMPLE_CHECKSUM = "simple_checksum"

class CRCVerifier:
    """CRC and checksum verification for binary frames"""
    
    def __init__(self, crc_type: CRCType = CRCType.CRC16_XMODEM):
        self.crc_type = crc_type
        self.crc_table_16 = self._generate_crc16_table()
        self.crc_table_32 = self._generate_crc32_table()
        
    def _generate_crc16_table(self) -> list:
        """Generate CRC-16 lookup table"""
        table = []
        for i in range(256):
            crc = i << 8
            for _ in range(8):
                if crc & 0x8000:
                    crc = (crc << 1) ^ 0x1021  # CRC-16-CCITT polynomial
                else:
                    crc <<= 1
                crc &= 0xFFFF
            table.append(crc)
        return table
        
    def _generate_crc32_table(self) -> list:
        """Generate CRC-32 lookup table"""
        table = []
        for i in range(256):
            crc = i
            for _ in range(8):
                if crc & 1:
                    crc = (crc >> 1) ^ 0xEDB88320  # CRC-32 polynomial
                else:
                    crc >>= 1
            table.append(crc)
        return table
        
    def calculate_crc16_ccitt(self, data: bytes) -> int:
        """Calculate CRC-16-CCITT"""
        crc = 0xFFFF
        for byte in data:
            crc = self.crc_table_16[(crc >> 8) ^ byte] ^ (crc << 8)
            crc &= 0xFFFF
        return crc
        
    def calculate_crc16_modbus(self, data: bytes) -> int:
        """Calculate CRC-16-MODBUS"""
        crc = 0xFFFF
        for byte in data:
            crc ^= byte
            for _ in range(8):
                if crc & 1:
                    crc = (crc >> 1) ^ 0xA001
                else:
                    crc >>= 1
        return crc
        
    def calculate_crc16_xmodem(self, data: bytes) -> int:
        """Calculate CRC-16-XMODEM"""
        return crc16_xmodem(data)
        
    def calculate_crc32(self, data: bytes) -> int:
        """Calculate CRC-32"""
        crc = 0xFFFFFFFF
        for byte in data:
            crc = self.crc_table_32[(crc ^ byte) & 0xFF] ^ (crc >> 8)
        return crc ^ 0xFFFFFFFF
        
    def calculate_simple_checksum(self, data: bytes) -> int:
        """Calculate simple 16-bit checksum"""
        checksum = 0
        for byte in data:
            checksum = (checksum + byte) & 0xFFFF
        return checksum
        
    def calculate(self, data: bytes) -> int:
        """Calculate CRC/checksum based on configured type"""
        if self.crc_type == CRCType.CRC16_CCITT:
            return self.calculate_crc16_ccitt(data)
        elif self.crc_type == CRCType.CRC16_MODBUS:
            return self.calculate_crc16_modbus(data)
        elif self.crc_type == CRC16_XMODEM:
            return self.calculate_crc16_xmodem(data)
        elif self.crc_type == CRCType.CRC32:
            return self.calculate_crc32(data)
        elif self.crc_type == CRCType.SIMPLE_CHECKSUM:
            return self.calculate_simple_checksum(data)
        else:
            raise ValueError(f"Unsupported CRC type: {self.crc_type}")
            
    def verify(self, data: bytes, expected_crc: int) -> bool:
        """Verify CRC/checksum"""
        calculated_crc = self.calculate(data)
        return calculated_crc == expected_crc
        
    def get_crc_size(self) -> int:
        """Get CRC size in bytes"""
        if self.crc_type == CRCType.CRC32:
            return 4
        else:
            return 2
            
    def get_crc_name(self) -> str:
        """Get CRC type name"""
        return self.crc_type.value

class BinaryFrameParser:
    """Binary frame parser with CRC verification"""
    
    def __init__(self, sync_word: bytes = b'\xAA\x55\xAA\x55', 
                 crc_type: CRCType = CRCType.CRC16_XMODEM):
        self.sync_word = sync_word
        self.crc_verifier = CRCVerifier(crc_type)
        self.frame_buffer = bytearray()
        
    def parse_frame(self, data: bytes) -> Optional[Tuple[bytes, bool]]:
        """Parse binary frame from data stream
        
        Returns:
            Tuple of (frame_data, crc_valid) or None if no complete frame
        """
        self.frame_buffer.extend(data)
        
        # Look for sync word
        sync_pos = self.frame_buffer.find(self.sync_word)
        if sync_pos == -1:
            # No sync word found, keep last few bytes
            if len(self.frame_buffer) > len(self.sync_word):
                self.frame_buffer = self.frame_buffer[-len(self.sync_word):]
            return None
            
        # Remove data before sync word
        if sync_pos > 0:
            self.frame_buffer = self.frame_buffer[sync_pos:]
            
        # Check if we have enough data for frame header
        min_header_size = len(self.sync_word) + 2 + self.crc_verifier.get_crc_size()  # sync + length + crc
        if len(self.frame_buffer) < min_header_size:
            return None
            
        # Parse frame header
        sync = self.frame_buffer[:len(self.sync_word)]
        length = struct.unpack('<H', self.frame_buffer[len(self.sync_word):len(self.sync_word)+2])[0]
        
        # Validate frame length
        if length < min_header_size or length > 1024:  # Sanity check
            # Invalid frame, skip one byte and try again
            self.frame_buffer = self.frame_buffer[1:]
            return None
            
        # Check if we have complete frame
        if len(self.frame_buffer) < length:
            return None
            
        # Extract frame data
        frame_data = self.frame_buffer[len(self.sync_word)+2:length-self.crc_verifier.get_crc_size()]
        received_crc = struct.unpack('<H', self.frame_buffer[length-self.crc_verifier.get_crc_size():length])[0]
        
        # Verify CRC
        crc_valid = self.crc_verifier.verify(frame_data, received_crc)
        
        # Remove processed frame
        self.frame_buffer = self.frame_buffer[length:]
        
        return (frame_data, crc_valid)
        
    def create_frame(self, data: bytes) -> bytes:
        """Create binary frame with CRC"""
        # Calculate CRC
        crc = self.crc_verifier.calculate(data)
        
        # Build frame: sync_word + length + data + crc
        length = len(self.sync_word) + 2 + len(data) + self.crc_verifier.get_crc_size()
        
        frame = bytearray()
        frame.extend(self.sync_word)
        frame.extend(struct.pack('<H', length))
        frame.extend(data)
        frame.extend(struct.pack('<H', crc))
        
        return bytes(frame)

# Example usage and testing
if __name__ == "__main__":
    import time
    
    # Setup logging
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    # Test CRC verification
    test_data = b"Hello, World!"
    
    print("Testing CRC verification...")
    
    # Test different CRC types
    crc_types = [CRCType.CRC16_CCITT, CRCType.CRC16_MODBUS, CRCType.CRC16_XMODEM, CRCType.CRC32]
    
    for crc_type in crc_types:
        verifier = CRCVerifier(crc_type)
        crc = verifier.calculate(test_data)
        is_valid = verifier.verify(test_data, crc)
        
        print(f"{crc_type.value}: {crc:04X} ({crc_size} bytes) - Valid: {is_valid}")
        
    # Test binary frame parsing
    print("\nTesting binary frame parsing...")
    
    parser = BinaryFrameParser()
    
    # Create test frame
    test_frame = parser.create_frame(test_data)
    print(f"Created frame: {test_frame.hex()}")
    
    # Parse frame
    parsed_data, crc_valid = parser.parse_frame(test_frame)
    print(f"Parsed data: {parsed_data}")
    print(f"CRC valid: {crc_valid}")
    
    # Test with corrupted data
    corrupted_frame = test_frame[:-1] + b'\xFF'  # Corrupt last byte
    parsed_data, crc_valid = parser.parse_frame(corrupted_frame)
    print(f"Corrupted frame CRC valid: {crc_valid}")
    
    print("CRC verification tests completed!")
