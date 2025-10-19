"""
Sync Data Queries Service
Handles database queries for sync_data table in cluster verification
"""
import json
import os
import sys
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from urllib.parse import urlparse

# Import logging system
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))
from utils.logger import get_bclient_logger

# Initialize logger
logger = get_bclient_logger('sync_data_queries')

# Global variables (will be injected)
db = None
SyncData = None


class SyncDataQueries:
    """Database queries for sync_data table"""
    
    def __init__(self, database):
        self.db = database
        self.min_batch_size = 3  # Minimum batch size for verification
    
    def get_valid_batches(self, channel_id: str, min_batch_size: int = None) -> List[Dict]:
        """
        Get valid batches from sync_data table
        
        Args:
            channel_id: Channel ID to filter by
            min_batch_size: Minimum batch size (default: 3)
            
        Returns:
            List of valid batch data
        """
        try:
            if min_batch_size is None:
                min_batch_size = self.min_batch_size
            
            logger.info(f"Querying valid batches for channel {channel_id} with min size {min_batch_size}")
            
            # Raw SQL query to get batches with more than min_batch_size records
            query = """
                SELECT 
                    batch_id,
                    COUNT(*) as record_count,
                    MIN(created_at) as first_record_time,
                    MAX(created_at) as last_record_time
                FROM sync_data 
                WHERE channel_id = :channel_id 
                GROUP BY batch_id 
                HAVING COUNT(*) > :min_batch_size
                ORDER BY first_record_time DESC
                LIMIT 10
            """
            
            result = self.db.session.execute(
                query, 
                {
                    'channel_id': channel_id,
                    'min_batch_size': min_batch_size
                }
            ).fetchall()
            
            valid_batches = []
            for row in result:
                batch_data = {
                    'batch_id': row.batch_id,
                    'record_count': row.record_count,
                    'first_record_time': row.first_record_time.isoformat() if row.first_record_time else None,
                    'last_record_time': row.last_record_time.isoformat() if row.last_record_time else None
                }
                valid_batches.append(batch_data)
            
            logger.info(f"Found {len(valid_batches)} valid batches for channel {channel_id}")
            return valid_batches
            
        except Exception as e:
            logger.error(f"Error querying valid batches: {e}")
            return []
    
    def get_batch_first_record(self, batch_id: str) -> Optional[Dict]:
        """
        Get the first record of a specific batch
        
        Args:
            batch_id: Batch ID to query
            
        Returns:
            First record data, or None if not found
        """
        try:
            logger.info(f"Getting first record for batch {batch_id}")
            
            # Query to get the first record of the batch
            query = """
                SELECT * FROM sync_data 
                WHERE batch_id = :batch_id 
                ORDER BY created_at ASC 
                LIMIT 1
            """
            
            result = self.db.session.execute(query, {'batch_id': batch_id}).fetchone()
            
            if result:
                # Convert row to dictionary
                record = dict(result._mapping)
                
                # Convert datetime objects to ISO format strings
                for key, value in record.items():
                    if isinstance(value, datetime):
                        record[key] = value.isoformat()
                
                logger.info(f"Found first record for batch {batch_id}")
                return record
            else:
                logger.warning(f"No records found for batch {batch_id}")
                return None
                
        except Exception as e:
            logger.error(f"Error getting batch first record: {e}")
            return None
    
    def get_batch_records(self, batch_id: str, limit: int = 10) -> List[Dict]:
        """
        Get records from a specific batch
        
        Args:
            batch_id: Batch ID to query
            limit: Maximum number of records to return
            
        Returns:
            List of batch records
        """
        try:
            logger.info(f"Getting records for batch {batch_id} (limit: {limit})")
            
            query = """
                SELECT * FROM sync_data 
                WHERE batch_id = :batch_id 
                ORDER BY created_at ASC 
                LIMIT :limit
            """
            
            result = self.db.session.execute(
                query, 
                {'batch_id': batch_id, 'limit': limit}
            ).fetchall()
            
            records = []
            for row in result:
                record = dict(row._mapping)
                
                # Convert datetime objects to ISO format strings
                for key, value in record.items():
                    if isinstance(value, datetime):
                        record[key] = value.isoformat()
                
                records.append(record)
            
            logger.info(f"Found {len(records)} records for batch {batch_id}")
            return records
            
        except Exception as e:
            logger.error(f"Error getting batch records: {e}")
            return []
    
    def get_channel_batch_summary(self, channel_id: str) -> Dict:
        """
        Get batch summary for a channel
        
        Args:
            channel_id: Channel ID to query
            
        Returns:
            Dict with batch summary statistics
        """
        try:
            logger.info(f"Getting batch summary for channel {channel_id}")
            
            # Query for batch statistics
            query = """
                SELECT 
                    COUNT(DISTINCT batch_id) as total_batches,
                    COUNT(*) as total_records,
                    AVG(batch_size) as avg_batch_size,
                    MAX(created_at) as latest_record_time,
                    MIN(created_at) as earliest_record_time
                FROM (
                    SELECT 
                        batch_id,
                        COUNT(*) as batch_size,
                        created_at
                    FROM sync_data 
                    WHERE channel_id = :channel_id 
                    GROUP BY batch_id, created_at
                ) batch_stats
            """
            
            result = self.db.session.execute(query, {'channel_id': channel_id}).fetchone()
            
            if result:
                summary = {
                    'total_batches': result.total_batches or 0,
                    'total_records': result.total_records or 0,
                    'avg_batch_size': float(result.avg_batch_size) if result.avg_batch_size else 0,
                    'latest_record_time': result.latest_record_time.isoformat() if result.latest_record_time else None,
                    'earliest_record_time': result.earliest_record_time.isoformat() if result.earliest_record_time else None
                }
                
                logger.info(f"Channel {channel_id} summary: {summary}")
                return summary
            else:
                logger.warning(f"No data found for channel {channel_id}")
                return {
                    'total_batches': 0,
                    'total_records': 0,
                    'avg_batch_size': 0,
                    'latest_record_time': None,
                    'earliest_record_time': None
                }
                
        except Exception as e:
            logger.error(f"Error getting channel batch summary: {e}")
            return {
                'total_batches': 0,
                'total_records': 0,
                'avg_batch_size': 0,
                'latest_record_time': None,
                'earliest_record_time': None
            }
    
    def check_batch_exists(self, batch_id: str) -> bool:
        """
        Check if a batch exists in the database
        
        Args:
            batch_id: Batch ID to check
            
        Returns:
            True if batch exists, False otherwise
        """
        try:
            logger.info(f"Checking if batch {batch_id} exists")
            
            query = "SELECT COUNT(*) as count FROM sync_data WHERE batch_id = :batch_id"
            result = self.db.session.execute(query, {'batch_id': batch_id}).fetchone()
            
            exists = result.count > 0 if result else False
            logger.info(f"Batch {batch_id} exists: {exists}")
            return exists
            
        except Exception as e:
            logger.error(f"Error checking batch existence: {e}")
            return False


# Global instance
sync_data_queries = None


def init_sync_data_queries(database):
    """Initialize sync data queries service"""
    global sync_data_queries
    sync_data_queries = SyncDataQueries(database)
    logger.info("Sync data queries service initialized")


def get_valid_batches_for_channel(channel_id: str, min_batch_size: int = 3) -> List[Dict]:
    """Get valid batches for a channel"""
    if not sync_data_queries:
        logger.error("Sync data queries service not initialized")
        return []
    
    return sync_data_queries.get_valid_batches(channel_id, min_batch_size)


def get_batch_first_record_data(batch_id: str) -> Optional[Dict]:
    """Get first record data for a batch"""
    if not sync_data_queries:
        logger.error("Sync data queries service not initialized")
        return None
    
    return sync_data_queries.get_batch_first_record(batch_id)


def get_user_recent_activity(user_id: str, days: int = 7) -> Dict:
    """
    Check if user has recent activity to determine if they're new
    
    Args:
        user_id: The user ID to check
        days: Number of days to look back for activity
        
    Returns:
        Dict containing activity information
    """
    try:
        logger.info(f"===== CHECKING RECENT ACTIVITY FOR USER {user_id} =====")
        
        
        # Calculate cutoff date
        cutoff_date = datetime.now() - timedelta(days=days)
        
        # Query recent activity
        recent_records = db.session.query(SyncData).filter(
            SyncData.user_id == user_id,
            SyncData.timestamp >= cutoff_date
        ).count()
        
        has_activity = recent_records > 0
        
        logger.info(f"===== USER {user_id} RECENT ACTIVITY CHECK =====")
        logger.info(f"Days checked: {days}")
        logger.info(f"Recent records: {recent_records}")
        logger.info(f"Has activity: {has_activity}")
        
        return {
            'has_recent_activity': has_activity,
            'count': recent_records,
            'days_checked': days
        }
        
    except Exception as e:
        logger.error(f"Error checking user recent activity: {e}")
        return {
            'has_recent_activity': False,
            'count': 0,
            'days_checked': days
        }


def get_user_browsing_patterns(user_id: str) -> Dict:
    """
    Analyze user's browsing patterns for consistency
    
    Args:
        user_id: The user ID to analyze
        
    Returns:
        Dict containing pattern analysis
    """
    try:
        logger.info(f"===== ANALYZING BROWSING PATTERNS FOR USER {user_id} =====")
        
        # Get user's recent browsing data
        recent_records = db.session.query(SyncData).filter(
            SyncData.user_id == user_id
        ).order_by(SyncData.timestamp.desc()).limit(50).all()
        
        if not recent_records:
            logger.info(f"===== NO BROWSING DATA FOR USER {user_id} =====")
            return {
                'has_consistent_patterns': True,  # Default to consistent if no data
                'score': 0.5,
                'pattern_count': 0
            }
        
        # Simple pattern analysis
        urls = [record.url for record in recent_records]
        unique_domains = set()
        
        for url in urls:
            try:
                domain = urlparse(url).netloc
                unique_domains.add(domain)
            except:
                continue
        
        # Calculate consistency score
        total_records = len(recent_records)
        unique_domains_count = len(unique_domains)
        
        # Higher score means more consistent (fewer unique domains)
        consistency_score = 1.0 - (unique_domains_count / total_records) if total_records > 0 else 0.5
        
        has_consistent_patterns = consistency_score > 0.3  # Threshold for consistency
        
        logger.info(f"===== USER {user_id} BROWSING PATTERN ANALYSIS =====")
        logger.info(f"Total records: {total_records}")
        logger.info(f"Unique domains: {unique_domains_count}")
        logger.info(f"Consistency score: {consistency_score:.2f}")
        logger.info(f"Has consistent patterns: {has_consistent_patterns}")
        
        return {
            'has_consistent_patterns': has_consistent_patterns,
            'score': consistency_score,
            'pattern_count': total_records,
            'unique_domains': unique_domains_count
        }
        
    except Exception as e:
        logger.error(f"Error analyzing user browsing patterns: {e}")
        return {
            'has_consistent_patterns': True,  # Default to consistent if error
            'score': 0.5,
            'pattern_count': 0
        }
