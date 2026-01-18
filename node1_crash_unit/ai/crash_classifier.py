"""
AI crash classifier
Uses machine learning to detect crash events from sensor data
"""

import numpy as np
from collections import deque


class CrashClassifier:
    """Machine learning classifier for crash detection"""
    
    def __init__(self):
        """Initialize the crash classifier"""
        self.feature_history = deque(maxlen=50)  # Recent features for temporal analysis
        self.threshold_accel = 15.0  # m/s² threshold for acceleration
        self.threshold_gyro = 600.0  # deg/s threshold for rotation
        self.threshold_jerk = 50.0  # m/s³ threshold for jerk (rate of acceleration change)
        
        # Simple rule-based classifier (can be replaced with trained ML model)
        self.weights = {
            'accel_magnitude': 0.4,
            'gyro_magnitude': 0.3,
            'jerk': 0.2,
            'impact': 0.1
        }
    
    def extract_features(self, sensor_data):
        """
        Extract features from sensor data for classification
        
        Args:
            sensor_data: Dictionary containing sensor readings
            
        Returns:
            dict: Extracted features
        """
        features = {}
        
        # Acceleration features
        if 'accelerometer' in sensor_data:
            accel = sensor_data['accelerometer']
            features['accel_x'] = accel.get('x', 0.0)
            features['accel_y'] = accel.get('y', 0.0)
            features['accel_z'] = accel.get('z', 0.0)
            features['accel_magnitude'] = accel.get('magnitude', 0.0)
        else:
            features['accel_magnitude'] = 0.0
        
        # Gyroscope features
        if 'gyroscope' in sensor_data:
            gyro = sensor_data['gyroscope']
            features['gyro_x'] = gyro.get('x', 0.0)
            features['gyro_y'] = gyro.get('y', 0.0)
            features['gyro_z'] = gyro.get('z', 0.0)
            features['gyro_magnitude'] = gyro.get('magnitude', 0.0)
        else:
            features['gyro_magnitude'] = 0.0
        
        # Impact feature
        features['impact'] = sensor_data.get('impact', 0.0) or 0.0
        
        # Calculate jerk (rate of change of acceleration)
        if len(self.feature_history) > 0:
            prev_accel = self.feature_history[-1].get('accel_magnitude', 9.8)
            current_accel = features['accel_magnitude']
            # Assuming 100Hz sampling rate
            features['jerk'] = abs(current_accel - prev_accel) * 100  # m/s³
        else:
            features['jerk'] = 0.0
        
        # Add to history
        self.feature_history.append(features.copy())
        
        return features
    
    def predict(self, features):
        """
        Predict if a crash has occurred
        
        Args:
            features: Extracted feature dictionary
            
        Returns:
            tuple: (is_crash: bool, confidence: float)
        """
        # Normalize features for scoring
        accel_score = min(features['accel_magnitude'] / self.threshold_accel, 1.0)
        gyro_score = min(features['gyro_magnitude'] / self.threshold_gyro, 1.0)
        jerk_score = min(features['jerk'] / self.threshold_jerk, 1.0)
        impact_score = 1.0 if features['impact'] > 5.0 else (features['impact'] / 5.0)
        
        # Weighted confidence score
        confidence = (
            accel_score * self.weights['accel_magnitude'] +
            gyro_score * self.weights['gyro_magnitude'] +
            jerk_score * self.weights['jerk'] +
            impact_score * self.weights['impact']
        )
        
        # Check temporal patterns (sudden change indicates crash)
        if len(self.feature_history) >= 3:
            recent_magnitudes = [f['accel_magnitude'] for f in list(self.feature_history)[-3:]]
            if max(recent_magnitudes) - min(recent_magnitudes) > 10.0:
                confidence *= 1.2  # Boost confidence for sudden changes
                confidence = min(confidence, 1.0)
        
        # Determine if crash
        is_crash = confidence > 0.7  # Base threshold
        
        # Hard thresholds (definite crashes)
        if features['accel_magnitude'] > self.threshold_accel:
            is_crash = True
            confidence = max(confidence, 0.9)
        
        if features['gyro_magnitude'] > self.threshold_gyro:
            is_crash = True
            confidence = max(confidence, 0.85)
        
        if features['impact'] and features['impact'] > 10.0:
            is_crash = True
            confidence = max(confidence, 0.95)
        
        return is_crash, confidence
    
    def load_model(self, model_path):
        """
        Load a trained ML model (placeholder for future implementation)
        
        Args:
            model_path: Path to saved model file
        """
        # TODO: Implement loading of trained model (e.g., TensorFlow, PyTorch, scikit-learn)
        print(f"Model loading from {model_path} not yet implemented")
        pass
    
    def retrain(self, training_data):
        """
        Retrain the classifier with new data (placeholder)
        
        Args:
            training_data: Training dataset
        """
        # TODO: Implement model retraining
        print("Model retraining not yet implemented")
        pass
