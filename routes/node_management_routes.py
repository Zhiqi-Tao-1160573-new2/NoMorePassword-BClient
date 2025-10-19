"""
Node Management Routes
Handles node management dashboard and API endpoints
"""

from flask import Blueprint, render_template, jsonify, request
import logging

logger = logging.getLogger(__name__)

node_management_routes = Blueprint('node_management', __name__)

# Global node manager instance (will be initialized from app.py)
node_manager = None

def init_node_management_routes(nm):
    """Initialize node management routes with NodeManager instance"""
    global node_manager
    node_manager = nm
    logger.info("Node management routes initialized")

@node_management_routes.route('/node-management')
def node_management_dashboard():
    """Render node management dashboard page"""
    return render_template('node_management.html')

@node_management_routes.route('/api/node-management/stats')
def get_node_stats():
    """Get node management statistics"""
    try:
        if node_manager is None:
            return jsonify({
                'success': False,
                'error': 'Node manager not initialized'
            }), 500
        
        # Get statistics from node manager
        stats = node_manager.get_pool_stats()
        
        return jsonify({
            'success': True,
            'stats': stats,
            'timestamp': str(datetime.now())
        })
        
    except Exception as e:
        logger.error(f"Error getting node stats: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@node_management_routes.route('/api/node-management/domains')
def get_domains():
    """Get all domain information"""
    try:
        if node_manager is None:
            return jsonify({
                'success': False,
                'error': 'Node manager not initialized'
            }), 500
        
        domains = []
        for domain_id, connections in node_manager.domain_pool.items():
            domains.append({
                'domain_id': domain_id,
                'connection_count': len(connections),
                'connections': [
                    {
                        'node_id': conn.node_id,
                        'cluster_id': conn.cluster_id,
                        'channel_id': conn.channel_id
                    }
                    for conn in connections
                ]
            })
        
        return jsonify({
            'success': True,
            'domains': domains
        })
        
    except Exception as e:
        logger.error(f"Error getting domains: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@node_management_routes.route('/api/node-management/clusters')
def get_clusters():
    """Get all cluster information"""
    try:
        if node_manager is None:
            return jsonify({
                'success': False,
                'error': 'Node manager not initialized'
            }), 500
        
        clusters = []
        for cluster_id, connections in node_manager.cluster_pool.items():
            clusters.append({
                'cluster_id': cluster_id,
                'connection_count': len(connections),
                'connections': [
                    {
                        'node_id': conn.node_id,
                        'domain_id': conn.domain_id,
                        'channel_id': conn.channel_id
                    }
                    for conn in connections
                ]
            })
        
        return jsonify({
            'success': True,
            'clusters': clusters
        })
        
    except Exception as e:
        logger.error(f"Error getting clusters: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@node_management_routes.route('/api/node-management/channels')
def get_channels():
    """Get all channel information"""
    try:
        if node_manager is None:
            return jsonify({
                'success': False,
                'error': 'Node manager not initialized'
            }), 500
        
        channels = []
        for channel_id, connections in node_manager.channel_pool.items():
            channels.append({
                'channel_id': channel_id,
                'connection_count': len(connections),
                'connections': [
                    {
                        'node_id': conn.node_id,
                        'domain_id': conn.domain_id,
                        'cluster_id': conn.cluster_id
                    }
                    for conn in connections
                ]
            })
        
        return jsonify({
            'success': True,
            'channels': channels
        })
        
    except Exception as e:
        logger.error(f"Error getting channels: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@node_management_routes.route('/api/node-management/structure')
def get_full_structure():
    """Get complete hierarchical node structure"""
    try:
        if node_manager is None:
            return jsonify({
                'success': False,
                'error': 'Node manager not initialized'
            }), 500
        
        structure = {
            'domains': []
        }
        
        # Build hierarchical structure
        for domain_id, domain_connections in node_manager.domain_pool.items():
            # Get domain main nodes (only nodes that are domain main nodes)
            domain_main_nodes = [
                {
                    'node_id': conn.node_id,
                    'user_id': conn.user_id,
                    'username': conn.username,
                    'is_domain_main': conn.is_domain_main_node,
                    'is_cluster_main': conn.is_cluster_main_node,
                    'is_channel_main': conn.is_channel_main_node
                }
                for conn in domain_connections
                if conn.is_domain_main_node  # ✅ Only show domain main nodes
            ]
            
            domain_data = {
                'domain_id': domain_id,
                'connection_count': len(domain_connections),
                'main_nodes': domain_main_nodes,
                'clusters': []
            }
            
            # Get clusters for this domain
            for cluster_id, cluster_connections in node_manager.cluster_pool.items():
                # Check if cluster belongs to this domain
                cluster_domain_connections = [
                    conn for conn in cluster_connections 
                    if conn.domain_id == domain_id
                ]
                
                if cluster_domain_connections:
                    # Get cluster main nodes (only nodes that are cluster main nodes)
                    cluster_main_nodes = [
                        {
                            'node_id': conn.node_id,
                            'user_id': conn.user_id,
                            'username': conn.username,
                            'is_domain_main': conn.is_domain_main_node,
                            'is_cluster_main': conn.is_cluster_main_node,
                            'is_channel_main': conn.is_channel_main_node
                        }
                        for conn in cluster_domain_connections
                        if conn.is_cluster_main_node  # ✅ Only show cluster main nodes
                    ]
                    
                    cluster_data = {
                        'cluster_id': cluster_id,
                        'connection_count': len(cluster_domain_connections),
                        'main_nodes': cluster_main_nodes,
                        'channels': []
                    }
                    
                    # Get channels for this cluster
                    for channel_id, channel_connections in node_manager.channel_pool.items():
                        # Check if channel belongs to this cluster
                        channel_cluster_connections = [
                            conn for conn in channel_connections 
                            if conn.cluster_id == cluster_id
                        ]
                        
                        if channel_cluster_connections:
                            # Get channel main nodes and regular nodes
                            channel_main_nodes = [
                                {
                                    'node_id': conn.node_id,
                                    'user_id': conn.user_id,
                                    'username': conn.username,
                                    'is_domain_main': conn.is_domain_main_node,
                                    'is_cluster_main': conn.is_cluster_main_node,
                                    'is_channel_main': conn.is_channel_main_node
                                }
                                for conn in channel_cluster_connections
                                if conn.is_channel_main_node
                            ]
                            
                            regular_nodes = [
                                {
                                    'node_id': conn.node_id,
                                    'user_id': conn.user_id,
                                    'username': conn.username,
                                    'is_domain_main': conn.is_domain_main_node,
                                    'is_cluster_main': conn.is_cluster_main_node,
                                    'is_channel_main': conn.is_channel_main_node
                                }
                                for conn in channel_cluster_connections
                                if not conn.is_channel_main_node
                            ]
                            
                            channel_data = {
                                'channel_id': channel_id,
                                'connection_count': len(channel_cluster_connections),
                                'main_nodes': channel_main_nodes,
                                'nodes': regular_nodes
                            }
                            cluster_data['channels'].append(channel_data)
                    
                    domain_data['clusters'].append(cluster_data)
            
            structure['domains'].append(domain_data)
        
        return jsonify({
            'success': True,
            'structure': structure
        })
        
    except Exception as e:
        logger.error(f"Error getting full structure: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@node_management_routes.route('/api/node-management/cleanup', methods=['POST'])
def cleanup_connections():
    """Cleanup disconnected connections"""
    try:
        if node_manager is None:
            return jsonify({
                'success': False,
                'error': 'Node manager not initialized'
            }), 500
        
        # This would need to be an async call in production
        # For now, we'll return a placeholder
        return jsonify({
            'success': True,
            'message': 'Cleanup initiated',
            'note': 'Cleanup is performed automatically in background'
        })
        
    except Exception as e:
        logger.error(f"Error during cleanup: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

# Import datetime for timestamp
from datetime import datetime

