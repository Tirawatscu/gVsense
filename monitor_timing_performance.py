#!/usr/bin/env python3
"""
Real-time GPS-MCU offset and timing performance monitor
Displays live statistics and identifies optimization opportunities
"""

import requests
import time
import subprocess
import json
from datetime import datetime
from collections import deque
import statistics

class TimingMonitor:
    def __init__(self, api_url="http://localhost:5000"):
        self.api_url = api_url
        self.offset_history = deque(maxlen=100)  # Last 100 samples
        self.drift_history = deque(maxlen=100)
        self.accuracy_history = deque(maxlen=100)
        self.start_time = time.time()
        
    def get_device_status(self):
        """Get current device status from API"""
        try:
            response = requests.get(f"{self.api_url}/api/status", timeout=2)
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            print(f"Warning: Could not fetch device status: {e}")
        return None
    
    def get_gps_alignment(self):
        """Get GPS alignment data"""
        try:
            response = requests.get(f"{self.api_url}/api/gps/alignment", timeout=2)
            if response.status_code == 200:
                return response.json()
        except Exception as e:
            print(f"Warning: Could not fetch GPS alignment: {e}")
        return None
    
    def get_chrony_stats(self):
        """Get chrony tracking statistics"""
        try:
            result = subprocess.run(['chronyc', 'tracking'], 
                                  capture_output=True, text=True, timeout=2)
            if result.returncode == 0:
                lines = result.stdout.strip().split('\n')
                stats = {}
                for line in lines:
                    if ':' in line:
                        key, value = line.split(':', 1)
                        stats[key.strip()] = value.strip()
                return stats
        except Exception as e:
            print(f"Warning: Could not fetch chrony stats: {e}")
        return None
    
    def analyze_performance(self):
        """Analyze timing performance and suggest optimizations"""
        analysis = {
            'status': 'UNKNOWN',
            'grade': 'N/A',
            'recommendations': []
        }
        
        if not self.offset_history:
            return analysis
        
        # Calculate statistics
        avg_offset = statistics.mean(self.offset_history)
        std_offset = statistics.stdev(self.offset_history) if len(self.offset_history) > 1 else 0
        max_offset = max(abs(x) for x in self.offset_history)
        
        if self.accuracy_history:
            avg_accuracy = statistics.mean(self.accuracy_history)
        else:
            avg_accuracy = None
        
        # Grade the performance
        if max_offset < 1.0 and std_offset < 0.5:
            analysis['status'] = 'EXCELLENT'
            analysis['grade'] = 'A+'
            analysis['recommendations'].append("✅ Timing performance is optimal")
        elif max_offset < 5.0 and std_offset < 2.0:
            analysis['status'] = 'GOOD'
            analysis['grade'] = 'A'
            analysis['recommendations'].append("✅ Timing performance is very good")
        elif max_offset < 10.0 and std_offset < 5.0:
            analysis['status'] = 'ACCEPTABLE'
            analysis['grade'] = 'B'
            analysis['recommendations'].append("⚠️  Consider monitoring for drift trends")
        else:
            analysis['status'] = 'NEEDS_ATTENTION'
            analysis['grade'] = 'C'
            analysis['recommendations'].append("🔴 Timing offset may need calibration")
        
        # Specific recommendations based on patterns
        if std_offset > 2.0:
            analysis['recommendations'].append(
                f"📊 High variance detected (σ={std_offset:.2f}ms) - Check GPS signal stability"
            )
        
        if abs(avg_offset) > 5.0:
            analysis['recommendations'].append(
                f"⚖️  Systematic offset detected ({avg_offset:+.2f}ms) - Consider MCU calibration adjustment"
            )
        
        if avg_accuracy and avg_accuracy > 10.0:
            analysis['recommendations'].append(
                f"🎯 Timing accuracy {avg_accuracy:.1f}μs - PPS may not be locked"
            )
        
        # Check for drift
        if len(self.drift_history) > 10:
            recent_drift = list(self.drift_history)[-10:]
            if all(d > 0 for d in recent_drift) or all(d < 0 for d in recent_drift):
                drift_rate = statistics.mean(recent_drift)
                analysis['recommendations'].append(
                    f"📈 Consistent drift detected ({drift_rate:+.3f} ppm) - Monitor for long-term stability"
                )
        
        analysis['statistics'] = {
            'avg_offset_ms': avg_offset,
            'std_offset_ms': std_offset,
            'max_offset_ms': max_offset,
            'avg_accuracy_us': avg_accuracy
        }
        
        return analysis
    
    def print_status(self, device_status, gps_alignment, chrony_stats):
        """Print formatted status"""
        print("\033[2J\033[H")  # Clear screen
        print("╔═══════════════════════════════════════════════════════════════════════════╗")
        print("║          📊 REAL-TIME GPS-MCU TIMING PERFORMANCE MONITOR                  ║")
        print("╚═══════════════════════════════════════════════════════════════════════════╝")
        print()
        
        runtime = time.time() - self.start_time
        print(f"⏱️  Runtime: {int(runtime//60)}m {int(runtime%60)}s | Samples: {len(self.offset_history)}")
        print()
        
        # Device Status
        if device_status:
            print("🔌 DEVICE STATUS")
            print("━" * 79)
            print(f"  Streaming:         {'✅ Yes' if device_status.get('streaming') else '❌ No'}")
            
            # These fields may not be in /api/status, check if they exist
            if device_status.get('timing_source'):
                print(f"  Timing Source:     {device_status.get('timing_source', 'N/A')}")
            if device_status.get('pps_valid') is not None:
                print(f"  PPS Valid:         {'✅ Yes' if device_status.get('pps_valid') else '❌ No'}")
            if device_status.get('timing_accuracy_us'):
                print(f"  Timing Accuracy:   ±{device_status.get('timing_accuracy_us')}μs")
            
            # Calibration data
            cal_ppm = device_status.get('calibration_ppm')
            if cal_ppm is not None and cal_ppm != 'N/A':
                try:
                    print(f"  Calibration:       {float(cal_ppm):.2f} ppm ({device_status.get('calibration_source', 'N/A')})")
                except (ValueError, TypeError):
                    pass
            
            # Stream info
            if device_status.get('stream_rate'):
                print(f"  Stream Rate:       {device_status.get('stream_rate')} Hz")
            if device_status.get('samples_generated'):
                print(f"  Samples Generated: {device_status.get('samples_generated'):,}")
            print()
        
        # GPS Alignment
        if gps_alignment and gps_alignment.get('status') == 'ok':
            align = gps_alignment.get('gps_alignment', {})
            mcu = gps_alignment.get('mcu_performance', {})
            perf = gps_alignment.get('performance_assessment', {})
            
            print("🛰️  GPS-MCU ALIGNMENT")
            print("━" * 79)
            
            offset_ms = align.get('gps_mcu_alignment_ms', 0)
            self.offset_history.append(offset_ms)
            
            print(f"  GPS-MCU Offset:    {offset_ms:+.3f} ms")
            print(f"  GPS Time Offset:   {align.get('gps_offset_ms', 0):+.3f} ms")
            print(f"  RMS Offset:        {align.get('rms_offset_ms', 0):+.3f} ms")
            print(f"  Frequency Error:   {align.get('frequency_error_ppm', 0):+.3f} ppm")
            
            if mcu.get('timing_accuracy_us'):
                self.accuracy_history.append(mcu['timing_accuracy_us'])
            
            print()
            print("📈 PERFORMANCE GRADE")
            print("━" * 79)
            print(f"  Score:  {perf.get('score', 0)}/100")
            print(f"  Grade:  {perf.get('grade', 'N/A')} {perf.get('status_emoji', '')}")
            print(f"  Status: {perf.get('summary', 'N/A')}")
            print()
        
        # Chrony Stats
        if chrony_stats:
            print("⏰ CHRONY TIME SYNCHRONIZATION")
            print("━" * 79)
            
            ref_id = chrony_stats.get('Reference ID', 'N/A')
            stratum = chrony_stats.get('Stratum', 'N/A')
            sys_time = chrony_stats.get('System time', 'N/A')
            freq_error = chrony_stats.get('Frequency', 'N/A')
            
            print(f"  Reference:         {ref_id}")
            print(f"  Stratum:           {stratum}")
            print(f"  System Time:       {sys_time}")
            print(f"  Frequency:         {freq_error}")
            
            # Extract drift if available
            if 'Frequency' in chrony_stats:
                try:
                    freq_str = chrony_stats['Frequency'].split()[0]
                    drift_ppm = float(freq_str)
                    self.drift_history.append(drift_ppm)
                except:
                    pass
            print()
        
        # Statistical Analysis
        if len(self.offset_history) > 1:
            analysis = self.analyze_performance()
            
            print("📊 STATISTICAL ANALYSIS")
            print("━" * 79)
            stats = analysis['statistics']
            print(f"  Average Offset:    {stats['avg_offset_ms']:+.3f} ms")
            print(f"  Std Deviation:     {stats['std_offset_ms']:.3f} ms")
            print(f"  Max Offset:        {stats['max_offset_ms']:.3f} ms")
            if stats['avg_accuracy_us']:
                print(f"  Avg Accuracy:      ±{stats['avg_accuracy_us']:.1f} μs")
            print()
            
            print(f"🎯 PERFORMANCE ANALYSIS: {analysis['status']} (Grade: {analysis['grade']})")
            print("━" * 79)
            for rec in analysis['recommendations']:
                print(f"  {rec}")
            print()
        
        # Offset trend visualization
        if len(self.offset_history) >= 10:
            print("📈 OFFSET TREND (Last 50 samples)")
            print("━" * 79)
            self._plot_ascii_chart(list(self.offset_history)[-50:])
            print()
        
        print("Press Ctrl+C to stop monitoring...")
    
    def _plot_ascii_chart(self, data, width=70, height=10):
        """Create ASCII chart of offset history"""
        if not data:
            return
        
        min_val = min(data)
        max_val = max(data)
        
        if min_val == max_val:
            print("  (All values equal)")
            return
        
        # Create chart
        for row in range(height):
            threshold = max_val - (row * (max_val - min_val) / (height - 1))
            line = "  "
            
            for val in data:
                if val >= threshold:
                    line += "█"
                else:
                    line += " "
            
            if row == 0:
                line += f" {max_val:+.2f}ms"
            elif row == height - 1:
                line += f" {min_val:+.2f}ms"
            elif row == height // 2:
                line += f" {(max_val + min_val)/2:+.2f}ms"
            
            print(line)
        
        print("  " + "─" * len(data))
        print(f"  ← Older    Time Progression    Newer →")
    
    def run(self, interval=5.0):
        """Run continuous monitoring"""
        print("Starting GPS-MCU timing performance monitor...")
        print("Collecting baseline data...\n")
        
        try:
            while True:
                device_status = self.get_device_status()
                gps_alignment = self.get_gps_alignment()
                chrony_stats = self.get_chrony_stats()
                
                self.print_status(device_status, gps_alignment, chrony_stats)
                
                time.sleep(interval)
                
        except KeyboardInterrupt:
            print("\n\n" + "═" * 79)
            print("MONITORING STOPPED - FINAL SUMMARY")
            print("═" * 79)
            
            if len(self.offset_history) > 1:
                analysis = self.analyze_performance()
                stats = analysis['statistics']
                
                print(f"\n📊 TIMING PERFORMANCE SUMMARY")
                print(f"   Runtime:           {int((time.time() - self.start_time) / 60)} minutes")
                print(f"   Samples Collected: {len(self.offset_history)}")
                print(f"   Average Offset:    {stats['avg_offset_ms']:+.3f} ms")
                print(f"   Std Deviation:     {stats['std_offset_ms']:.3f} ms")
                print(f"   Max Offset:        {stats['max_offset_ms']:.3f} ms")
                print(f"\n   Overall Grade:     {analysis['grade']} ({analysis['status']})")
                print(f"\n🎯 RECOMMENDATIONS:")
                for rec in analysis['recommendations']:
                    print(f"   {rec}")
            
            print("\n" + "═" * 79)

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Monitor GPS-MCU timing performance")
    parser.add_argument('--interval', type=float, default=5.0,
                       help='Monitoring interval in seconds (default: 5.0)')
    parser.add_argument('--url', default='http://localhost:5000',
                       help='gVsense API URL (default: http://localhost:5000)')
    
    args = parser.parse_args()
    
    monitor = TimingMonitor(api_url=args.url)
    monitor.run(interval=args.interval)
