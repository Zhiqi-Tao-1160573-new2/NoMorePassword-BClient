import uuid
import asyncio
import logging
import sys
import os
import traceback
import json
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass
from websockets.exceptions import ConnectionClosed

# Import logging system
sys.path.append(os.path.join(os.path.dirname(__file__), '.'))
from utils.logger import get_bclient_logger

@dataclass
class ClientConnection:
    """Represents a WebSocket connection to a C-Client"""
    websocket: Any
    node_id: Optional[str] = None
    user_id: Optional[str] = None
    username: Optional[str] = None
    domain_id: Optional[str] = None
    cluster_id: Optional[str] = None
    channel_id: Optional[str] = None
    # Main node IDs for determining node type
    domain_main_node_id: Optional[str] = None
    cluster_main_node_id: Optional[str] = None
    channel_main_node_id: Optional[str] = None
    # Node type flags
    is_domain_main_node: bool = False
    is_cluster_main_node: bool = False
    is_channel_main_node: bool = False

class NodeManager:
    """
    B-Client Node Management System
    Manages hierarchical node structure with connection pools
    """
    
    def __init__(self):
        # Initialize logging system
        self.logger = get_bclient_logger('nodemanager')
        
        # Connection pools: key -> list of ClientConnection
        self.domain_pool: Dict[str, List[ClientConnection]] = {}
        self.cluster_pool: Dict[str, List[ClientConnection]] = {}
        self.channel_pool: Dict[str, List[ClientConnection]] = {}
        
        # Fast lookup indexes for O(1) removal by node_id
        self.domain_node_index: Dict[str, Dict[str, ClientConnection]] = {}    # domain_id -> {node_id: ClientConnection}
        self.cluster_node_index: Dict[str, Dict[str, ClientConnection]] = {}   # cluster_id -> {node_id: ClientConnection}
        self.channel_node_index: Dict[str, Dict[str, ClientConnection]] = {}   # channel_id -> {node_id: ClientConnection}
        
        # Request tracking for async operations
        self.pending_requests: Dict[str, asyncio.Future] = {}
        
        self.logger.info("NodeManager initialized with connection pools")
    
    # ===================== C-Client Registration =====================
    
    async def handle_new_connection(self, websocket: Any, nmp_params: Dict[str, Any]) -> ClientConnection:
        """
        Handle new C-Client WebSocket connection
        Register client and assign to node structure if needed
        
        Args:
            websocket: WebSocket connection
            nmp_params: NMP parameters from URL
            
        Returns:
            ClientConnection instance
        """
        try:
            self.logger.info("=" * 80)
            self.logger.info("🔧 NODEMANAGER: handle_new_connection() CALLED")
            self.logger.info(f"📋 NMP Parameters received: {nmp_params}")
            self.logger.info("=" * 80)
            
            # Register the C-Client
            self.logger.info("📝 Step 1: Calling register_c_client()...")
            connection = self.register_c_client(websocket, nmp_params)
            self.logger.info(f"✅ Step 1 completed: Connection created for node {connection.node_id}")
            
            # Check if client needs node assignment
            self.logger.info(f"🔍 Step 2: Checking if assignment needed...")
            self.logger.info(f"   connection.domain_id = {connection.domain_id}")
            self.logger.info(f"   connection.cluster_id = {connection.cluster_id}")
            self.logger.info(f"   connection.channel_id = {connection.channel_id}")
            
            # Check if full hierarchy exists
            needs_assignment = False
            
            if not connection.domain_id:
                self.logger.info(f"⚠️ Client missing domain_id, needs full assignment")
                needs_assignment = True
            elif not connection.cluster_id:
                self.logger.info(f"⚠️ Client has domain but missing cluster_id, needs cluster/channel assignment")
                needs_assignment = True
            elif not connection.channel_id:
                self.logger.info(f"⚠️ Client has domain/cluster but missing channel_id, needs channel assignment")
                needs_assignment = True
            
            if needs_assignment:
                self.logger.info("📍 Step 3: Calling assign_new_client()...")
                await self.assign_new_client(connection)
                self.logger.info("✅ Step 3 completed: Client assigned to node structure")
            else:
                self.logger.info(f"✅ Client already has full hierarchy (domain/cluster/channel), skipping assignment")
            
            self.logger.info("=" * 80)
            self.logger.info("🎉 NODEMANAGER: handle_new_connection() COMPLETED")
            self.logger.info(f"   Node ID: {connection.node_id}")
            self.logger.info(f"   Domain ID: {connection.domain_id}")
            self.logger.info(f"   Cluster ID: {connection.cluster_id}")
            self.logger.info(f"   Channel ID: {connection.channel_id}")
            self.logger.info(f"   Is Domain Main: {connection.is_domain_main_node}")
            self.logger.info(f"   Is Cluster Main: {connection.is_cluster_main_node}")
            self.logger.info(f"   Is Channel Main: {connection.is_channel_main_node}")
            self.logger.info("=" * 80)
            
            return connection
            
        except Exception as e:
            self.logger.error("=" * 80)
            self.logger.error(f"❌ NODEMANAGER: ERROR in handle_new_connection()")
            self.logger.error(f"   Error: {e}")
            traceback.print_exc()
            self.logger.error("=" * 80)
            raise
    
    async def assign_new_client(self, connection: ClientConnection) -> bool:
        """
        Assign a new C-Client to node structure
        Creates domain/cluster/channel hierarchy if needed
        
        Args:
            connection: ClientConnection instance
            
        Returns:
            True if assignment successful
        """
        try:
            self.logger.info("─" * 80)
            self.logger.info(f"🆕 NODEMANAGER: assign_new_client() STARTED")
            self.logger.info(f"   Client node_id: {connection.node_id}")
            self.logger.info(f"   Current state: domain_id={connection.domain_id}, cluster_id={connection.cluster_id}, channel_id={connection.channel_id}")
            
            # Check what level needs to be created
            if not connection.domain_id:
                # No domain - create full hierarchy
                self.logger.info("📍 No domain_id - need to create full hierarchy")
                self.logger.info(f"🔍 Checking domain_pool...")
                self.logger.info(f"   domain_pool size: {len(self.domain_pool)}")
                self.logger.info(f"   domain_pool keys: {list(self.domain_pool.keys())}")
                
                if len(self.domain_pool) == 0:
                    self.logger.info("📍 No domains exist, creating first domain node")
                    self.logger.info("🏗️ Calling new_domain_node() to create full hierarchy...")
                    result = await self.new_domain_node(connection)
                    self.logger.info(f"─" * 80)
                    return result
                
                # Try to assign to existing domain
                self.logger.info(f"📍 Found {len(self.domain_pool)} existing domain(s), trying to assign...")
                for domain_id, domain_connections in self.domain_pool.items():
                    if len(domain_connections) == 0:
                        continue
                    domain_main_connection = domain_connections[0]
                    success = await self.assign_to_domain(connection, domain_id, domain_main_connection.node_id)
                    if success:
                        self.logger.info(f"✅ Successfully assigned to domain {domain_id}")
                        self.logger.info(f"─" * 80)
                        return True
                
                # All domains full, create new
                self.logger.info("📍 All domains full, creating new domain")
                result = await self.new_domain_node(connection)
                self.logger.info(f"─" * 80)
                return result
                
            elif not connection.cluster_id:
                # Has domain but no cluster - create cluster and channel
                self.logger.info(f"📍 Has domain_id but no cluster_id - need to create cluster/channel")
                self.logger.info(f"🏗️ Calling new_cluster_node() for domain {connection.domain_id}...")
                result = await self.new_cluster_node(connection, connection.domain_id)
                self.logger.info(f"─" * 80)
                return result
                
            elif not connection.channel_id:
                # Has domain/cluster but no channel - create channel only
                self.logger.info(f"📍 Has domain/cluster but no channel_id - need to create channel")
                self.logger.info(f"🏗️ Calling new_channel_node() for cluster {connection.cluster_id}...")
                result = await self.new_channel_node(connection, connection.domain_id, connection.cluster_id)
                self.logger.info(f"─" * 80)
                return result
            
            # Should not reach here
            self.logger.warning("⚠️ Client has full hierarchy but assign_new_client was called")
            self.logger.info(f"─" * 80)
            return True
            
        except Exception as e:
            self.logger.error(f"❌ NODEMANAGER: ERROR in assign_new_client()")
            self.logger.error(f"   Error: {e}")
            traceback.print_exc()
            self.logger.error(f"─" * 80)
            return False
    
    def register_c_client(self, websocket: Any, nmp_params: Dict[str, Any]) -> ClientConnection:
        """
        Register a C-Client connection with NMP parameters
        Determines node type based on main node IDs and adds to appropriate pools
        
        Args:
            websocket: WebSocket connection
            nmp_params: NMP parameters including:
                - nmp_user_id
                - nmp_username
                - nmp_node_id
                - nmp_domain_main_node_id
                - nmp_cluster_main_node_id
                - nmp_channel_main_node_id
                - nmp_domain_id
                - nmp_cluster_id
                - nmp_channel_id
        
        Returns:
            ClientConnection instance
        """
        try:
            self.logger.info("─" * 80)
            self.logger.info("📝 NODEMANAGER: register_c_client() STARTED")
            
            # Extract parameters
            node_id = nmp_params.get('nmp_node_id')
            user_id = nmp_params.get('nmp_user_id')
            username = nmp_params.get('nmp_username')
            domain_main_node_id = nmp_params.get('nmp_domain_main_node_id')
            cluster_main_node_id = nmp_params.get('nmp_cluster_main_node_id')
            channel_main_node_id = nmp_params.get('nmp_channel_main_node_id')
            domain_id = nmp_params.get('nmp_domain_id')
            cluster_id = nmp_params.get('nmp_cluster_id')
            channel_id = nmp_params.get('nmp_channel_id')
            
            self.logger.info(f"📋 Registering C-Client: node_id={node_id}")
            self.logger.info(f"📋 NMP Parameters:")
            self.logger.info(f"   node_id: {node_id}")
            self.logger.info(f"   user_id: {user_id}")
            self.logger.info(f"   username: {username}")
            self.logger.info(f"   domain_main_node_id: {domain_main_node_id}")
            self.logger.info(f"   cluster_main_node_id: {cluster_main_node_id}")
            self.logger.info(f"   channel_main_node_id: {channel_main_node_id}")
            self.logger.info(f"   domain_id: {domain_id}")
            self.logger.info(f"   cluster_id: {cluster_id}")
            self.logger.info(f"   channel_id: {channel_id}")
            
            # Create connection object
            connection = ClientConnection(
                websocket=websocket,
                node_id=node_id,
                user_id=user_id,
                username=username,
                domain_id=domain_id,
                cluster_id=cluster_id,
                channel_id=channel_id,
                domain_main_node_id=domain_main_node_id,
                cluster_main_node_id=cluster_main_node_id,
                channel_main_node_id=channel_main_node_id
            )
            
            self.logger.info("🔍 Determining node type by ID comparison...")
            
            # Determine node type by comparing node_id with main node IDs
            self.logger.info(f"🔍 Checking if Domain main node:")
            self.logger.info(f"   node_id ({node_id}) == domain_main_node_id ({domain_main_node_id})?")
            if domain_main_node_id and node_id == domain_main_node_id:
                connection.is_domain_main_node = True
                self.logger.info(f"  ✅ YES - Node {node_id} is a DOMAIN main node")
            else:
                self.logger.info(f"  ❌ NO - Not a domain main node")
            
            self.logger.info(f"🔍 Checking if Cluster main node:")
            self.logger.info(f"   node_id ({node_id}) == cluster_main_node_id ({cluster_main_node_id})?")
            if cluster_main_node_id and node_id == cluster_main_node_id:
                connection.is_cluster_main_node = True
                self.logger.info(f"  ✅ YES - Node {node_id} is a CLUSTER main node")
            else:
                self.logger.info(f"  ❌ NO - Not a cluster main node")
            
            self.logger.info(f"🔍 Checking if Channel main node:")
            self.logger.info(f"   node_id ({node_id}) == channel_main_node_id ({channel_main_node_id})?")
            if channel_main_node_id and node_id == channel_main_node_id:
                connection.is_channel_main_node = True
                self.logger.info(f"  ✅ YES - Node {node_id} is a CHANNEL main node")
            else:
                self.logger.info(f"  ❌ NO - Not a channel main node")
            
            self.logger.info("📦 Adding to connection pools...")
            self.logger.info(f"  📋 Node type: Domain={'MAIN' if connection.is_domain_main_node else 'REGULAR'}, Cluster={'MAIN' if connection.is_cluster_main_node else 'REGULAR'}, Channel={'MAIN' if connection.is_channel_main_node else 'REGULAR'}")
            
            # Add to domain pool if domain_id exists (main node or regular node)
            if domain_id:
                self.add_to_domain_pool(domain_id, connection)
                node_type = "MAIN" if connection.is_domain_main_node else "regular"
                self.logger.info(f"  ✅ Added {node_type} node to domain_pool[{domain_id}]")
            
            # Add to cluster pool if cluster_id exists (main node or regular node)
            if cluster_id:
                self.add_to_cluster_pool(cluster_id, connection)
                node_type = "MAIN" if connection.is_cluster_main_node else "regular"
                self.logger.info(f"  ✅ Added {node_type} node to cluster_pool[{cluster_id}]")
            
            # Add to channel pool if channel_id exists (main node or regular node)
            if channel_id:
                self.add_to_channel_pool(channel_id, connection)
                node_type = "MAIN" if connection.is_channel_main_node else "regular"
                self.logger.info(f"  ✅ Added {node_type} node to channel_pool[{channel_id}]")
            
            # If not a main node at any level, add to channel pool as regular node
            if not (connection.is_domain_main_node or connection.is_cluster_main_node or connection.is_channel_main_node):
                self.logger.info(f"  ℹ️ Not a main node at any level")
                if channel_id:
                    self.add_to_channel_pool(channel_id, connection)
                    self.logger.info(f"  ✅ Added to channel_pool[{channel_id}] as regular node")
                else:
                    self.logger.warning(f"  ⚠️ Regular node without channel_id, NOT added to any pool")
            
            # Display pool stats
            stats = self.get_pool_stats()
            self.logger.info(f"📊 Current pool stats after registration:")
            self.logger.info(f"   Total domains: {stats['domains']}")
            self.logger.info(f"   Total clusters: {stats['clusters']}")
            self.logger.info(f"   Total channels: {stats['channels']}")
            self.logger.info(f"   Total connections: {stats['total_connections']}")
            
            self.logger.info(f"✅ NODEMANAGER: register_c_client() COMPLETED for {node_id}")
            self.logger.info("─" * 80)
            return connection
            
        except Exception as e:
            self.logger.error(f"Error registering C-Client: {e}")
            raise
    
    # ===================== Connection Pool Management =====================
    
    def add_to_domain_pool(self, domain_id: str, connection: ClientConnection):
        """Add connection to domain pool"""
        if domain_id not in self.domain_pool:
            self.domain_pool[domain_id] = []
            self.domain_node_index[domain_id] = {}
        
        # Check if this connection already exists using fast index lookup
        if connection.node_id in self.domain_node_index[domain_id]:
            # Connection already exists, update it instead of adding duplicate
            existing_connection = self.domain_node_index[domain_id][connection.node_id]
            self.logger.info(f"Connection for node {connection.node_id} already exists in domain pool {domain_id}, updating...")
            # Update the existing connection with new websocket and user info
            existing_connection.websocket = connection.websocket
            existing_connection.user_id = connection.user_id
            existing_connection.username = connection.username
            existing_connection.is_domain_main_node = connection.is_domain_main_node
            existing_connection.is_cluster_main_node = connection.is_cluster_main_node
            existing_connection.is_channel_main_node = connection.is_channel_main_node
            self.logger.info(f"Updated existing connection for node {connection.node_id} in domain pool {domain_id}")
        else:
            # New connection, add it to the pool and index
            self.domain_pool[domain_id].append(connection)
            self.domain_node_index[domain_id][connection.node_id] = connection
            connection.domain_id = domain_id
            self.logger.info(f"Added new connection to domain pool {domain_id}")
    
    def add_to_cluster_pool(self, cluster_id: str, connection: ClientConnection):
        """Add connection to cluster pool"""
        if cluster_id not in self.cluster_pool:
            self.cluster_pool[cluster_id] = []
            self.cluster_node_index[cluster_id] = {}
        
        # Check if this connection already exists using fast index lookup
        if connection.node_id in self.cluster_node_index[cluster_id]:
            # Connection already exists, update it instead of adding duplicate
            existing_connection = self.cluster_node_index[cluster_id][connection.node_id]
            self.logger.info(f"Connection for node {connection.node_id} already exists in cluster pool {cluster_id}, updating...")
            # Update the existing connection with new websocket and user info
            existing_connection.websocket = connection.websocket
            existing_connection.user_id = connection.user_id
            existing_connection.username = connection.username
            existing_connection.is_domain_main_node = connection.is_domain_main_node
            existing_connection.is_cluster_main_node = connection.is_cluster_main_node
            existing_connection.is_channel_main_node = connection.is_channel_main_node
            self.logger.info(f"Updated existing connection for node {connection.node_id} in cluster pool {cluster_id}")
        else:
            # New connection, add it to the pool and index
            self.cluster_pool[cluster_id].append(connection)
            self.cluster_node_index[cluster_id][connection.node_id] = connection
            connection.cluster_id = cluster_id
            self.logger.info(f"Added new connection to cluster pool {cluster_id}")
    
    def add_to_channel_pool(self, channel_id: str, connection: ClientConnection):
        """Add connection to channel pool"""
        if channel_id not in self.channel_pool:
            self.channel_pool[channel_id] = []
            self.channel_node_index[channel_id] = {}
        
        # Check if this connection already exists using fast index lookup
        if connection.node_id in self.channel_node_index[channel_id]:
            # Connection already exists, update it instead of adding duplicate
            existing_connection = self.channel_node_index[channel_id][connection.node_id]
            self.logger.info(f"Connection for node {connection.node_id} already exists in channel pool {channel_id}, updating...")
            # Update the existing connection with new websocket and user info
            existing_connection.websocket = connection.websocket
            existing_connection.user_id = connection.user_id
            existing_connection.username = connection.username
            existing_connection.is_domain_main_node = connection.is_domain_main_node
            existing_connection.is_cluster_main_node = connection.is_cluster_main_node
            existing_connection.is_channel_main_node = connection.is_channel_main_node
            self.logger.info(f"Updated existing connection for node {connection.node_id} in channel pool {channel_id}")
        else:
            # New connection, add it to the pool and index
            self.channel_pool[channel_id].append(connection)
            self.channel_node_index[channel_id][connection.node_id] = connection
            connection.channel_id = channel_id
            self.logger.info(f"Added new connection to channel pool {channel_id}")
    
    def remove_connection(self, connection: ClientConnection):
        """Remove connection from all pools with proper hierarchy cleanup"""
        
        self.logger.info(f"🔧 NodeManager: Starting connection removal process")
        self.logger.info(f"🔧 NodeManager: Connection details - node_id: {connection.node_id}, user_id: {connection.user_id}")
        self.logger.info(f"🔧 NodeManager: Connection hierarchy - domain: {connection.domain_id}, cluster: {connection.cluster_id}, channel: {connection.channel_id}")
        self.logger.info(f"🔧 NodeManager: Connection types - domain_main: {connection.is_domain_main_node}, cluster_main: {connection.is_cluster_main_node}, channel_main: {connection.is_channel_main_node}")
        
        # 1. Remove connection from all pools (using WebSocket object reference)
        removed_from = []
        
        # Remove from channel pool using O(1) index lookup
        if connection.channel_id and connection.channel_id in self.channel_pool:
            original_count = len(self.channel_pool[connection.channel_id])
            self.logger.info(f"🔧 NodeManager: Channel pool {connection.channel_id} has {original_count} connections before removal")
            
            # Use fast index lookup for O(1) removal
            if connection.node_id in self.channel_node_index[connection.channel_id]:
                # Remove from index first
                del self.channel_node_index[connection.channel_id][connection.node_id]
                
                # Remove from pool using list comprehension (still O(n) but only one pass)
                self.channel_pool[connection.channel_id] = [
                    conn for conn in self.channel_pool[connection.channel_id] 
                    if conn.node_id != connection.node_id
                ]
                
                removed_from.append(f"channel({connection.channel_id})")
                self.logger.info(f"✅ NodeManager: Successfully removed connection from channel pool {connection.channel_id} using O(1) index lookup for node_id: {connection.node_id}")
                
                # Check if channel pool can be deleted
                if self._should_remove_channel_pool(connection.channel_id):
                    del self.channel_pool[connection.channel_id]
                    del self.channel_node_index[connection.channel_id]
                    removed_from.append(f"channel_pool({connection.channel_id})")
                    self.logger.info(f"🗑️ NodeManager: Removed empty channel pool and index: {connection.channel_id}")
                else:
                    self.logger.info(f"📊 NodeManager: Channel pool {connection.channel_id} still has connections, keeping pool")
            else:
                self.logger.warning(f"⚠️ NodeManager: Node {connection.node_id} not found in channel index {connection.channel_id}")
        
        # Remove from cluster pool using O(1) index lookup
        if connection.cluster_id and connection.cluster_id in self.cluster_pool:
            original_count = len(self.cluster_pool[connection.cluster_id])
            self.logger.info(f"🔧 NodeManager: Cluster pool {connection.cluster_id} has {original_count} connections before removal")
            
            # Use fast index lookup for O(1) removal
            if connection.node_id in self.cluster_node_index[connection.cluster_id]:
                # Remove from index first
                del self.cluster_node_index[connection.cluster_id][connection.node_id]
                
                # Remove from pool using list comprehension (still O(n) but only one pass)
                self.cluster_pool[connection.cluster_id] = [
                    conn for conn in self.cluster_pool[connection.cluster_id] 
                    if conn.node_id != connection.node_id
                ]
                
                removed_from.append(f"cluster({connection.cluster_id})")
                self.logger.info(f"✅ NodeManager: Successfully removed connection from cluster pool {connection.cluster_id} using O(1) index lookup for node_id: {connection.node_id}")
                
                # Check if cluster pool can be deleted
                if self._should_remove_cluster_pool(connection.cluster_id):
                    del self.cluster_pool[connection.cluster_id]
                    del self.cluster_node_index[connection.cluster_id]
                    removed_from.append(f"cluster_pool({connection.cluster_id})")
                    self.logger.info(f"🗑️ NodeManager: Removed empty cluster pool and index: {connection.cluster_id}")
                else:
                    self.logger.info(f"📊 NodeManager: Cluster pool {connection.cluster_id} still has connections, keeping pool")
            else:
                self.logger.warning(f"⚠️ NodeManager: Node {connection.node_id} not found in cluster index {connection.cluster_id}")
        
        # Remove from domain pool using O(1) index lookup
        if connection.domain_id and connection.domain_id in self.domain_pool:
            original_count = len(self.domain_pool[connection.domain_id])
            self.logger.info(f"🔧 NodeManager: Domain pool {connection.domain_id} has {original_count} connections before removal")
            
            # Use fast index lookup for O(1) removal
            if connection.node_id in self.domain_node_index[connection.domain_id]:
                # Remove from index first
                del self.domain_node_index[connection.domain_id][connection.node_id]
                
                # Remove from pool using list comprehension (still O(n) but only one pass)
                self.domain_pool[connection.domain_id] = [
                    conn for conn in self.domain_pool[connection.domain_id] 
                    if conn.node_id != connection.node_id
                ]
                
                removed_from.append(f"domain({connection.domain_id})")
                self.logger.info(f"✅ NodeManager: Successfully removed connection from domain pool {connection.domain_id} using O(1) index lookup for node_id: {connection.node_id}")
                
                # Check if domain pool can be deleted
                if self._should_remove_domain_pool(connection.domain_id):
                    del self.domain_pool[connection.domain_id]
                    del self.domain_node_index[connection.domain_id]
                    removed_from.append(f"domain_pool({connection.domain_id})")
                    self.logger.info(f"🗑️ NodeManager: Removed empty domain pool and index: {connection.domain_id}")
                else:
                    self.logger.info(f"📊 NodeManager: Domain pool {connection.domain_id} still has connections, keeping pool")
            else:
                self.logger.warning(f"⚠️ NodeManager: Node {connection.node_id} not found in domain index {connection.domain_id}")
        
        # Log final pool status
        total_domains = len(self.domain_pool)
        total_clusters = len(self.cluster_pool)
        total_channels = len(self.channel_pool)
        self.logger.info(f"📊 NodeManager: Final pool status after removal - Domains: {total_domains}, Clusters: {total_clusters}, Channels: {total_channels}")
        
        if removed_from:
            self.logger.info(f"✅ NodeManager: Successfully removed connection from: {', '.join(removed_from)}")
        else:
            self.logger.warning(f"⚠️ NodeManager: Connection was not found in any hierarchy pools")

    def _should_remove_channel_pool(self, channel_id: str) -> bool:
        """Check if channel pool should be removed"""
        self.logger.info(f"🔍 NodeManager: Checking if channel pool {channel_id} should be removed")
        
        # Channel pool can be deleted if:
        # 1. Pool has no connections
        # 2. Or pool only has main node connection, but main node is also disconnected
        if channel_id not in self.channel_pool:
            self.logger.info(f"✅ NodeManager: Channel pool {channel_id} not found, should be removed")
            return True
            
        remaining_connections = self.channel_pool[channel_id]
        self.logger.info(f"🔍 NodeManager: Channel pool {channel_id} has {len(remaining_connections)} remaining connections")
        
        if not remaining_connections:
            self.logger.info(f"✅ NodeManager: Channel pool {channel_id} is empty, should be removed")
            return True
            
        # If only main node remains and main node is disconnected, can be deleted
        if len(remaining_connections) == 1:
            main_connection = remaining_connections[0]
            self.logger.info(f"🔍 NodeManager: Channel pool {channel_id} has 1 connection, checking if it's a closed main node")
            self.logger.info(f"🔍 NodeManager: Connection is_channel_main_node: {main_connection.is_channel_main_node}")
            
            # Check if the main node connection is still valid
            is_connection_valid = self._is_websocket_valid(main_connection.websocket)
            self.logger.info(f"🔍 NodeManager: Connection is_valid: {is_connection_valid}")
            
            if (main_connection.is_channel_main_node and not is_connection_valid):
                self.logger.info(f"✅ NodeManager: Channel pool {channel_id} has only invalid main node, should be removed")
                return True
            else:
                self.logger.info(f"📊 NodeManager: Channel pool {channel_id} has active connection, keeping pool")
        else:
            self.logger.info(f"📊 NodeManager: Channel pool {channel_id} has multiple connections, keeping pool")
                
        return False

    def _should_remove_cluster_pool(self, cluster_id: str) -> bool:
        """Check if cluster pool should be removed"""
        self.logger.info(f"🔍 NodeManager: Checking if cluster pool {cluster_id} should be removed")
        
        # Cluster pool can be deleted if:
        # 1. Pool has no connections
        # 2. Or pool only has main node connection, but main node is also disconnected
        # 3. Or all channels under this cluster have been deleted
        if cluster_id not in self.cluster_pool:
            self.logger.info(f"✅ NodeManager: Cluster pool {cluster_id} not found, should be removed")
            return True
            
        remaining_connections = self.cluster_pool[cluster_id]
        self.logger.info(f"🔍 NodeManager: Cluster pool {cluster_id} has {len(remaining_connections)} remaining connections")
        
        if not remaining_connections:
            self.logger.info(f"✅ NodeManager: Cluster pool {cluster_id} is empty, should be removed")
            return True
            
        # Check if there are still related channels
        active_channels = []
        for conn in remaining_connections:
            if conn.channel_id and conn.channel_id in self.channel_pool:
                active_channels.append(conn.channel_id)
        
        self.logger.info(f"🔍 NodeManager: Cluster pool {cluster_id} has active channels: {active_channels}")
        
        if not active_channels:
            self.logger.info(f"✅ NodeManager: Cluster pool {cluster_id} has no active channels, should be removed")
            return True
        else:
            self.logger.info(f"📊 NodeManager: Cluster pool {cluster_id} has active channels, keeping pool")
            
        return False

    def _should_remove_domain_pool(self, domain_id: str) -> bool:
        """Check if domain pool should be removed"""
        self.logger.info(f"🔍 NodeManager: Checking if domain pool {domain_id} should be removed")
        
        # Domain pool can be deleted if:
        # 1. Pool has no connections
        # 2. Or pool only has main node connection, but main node is also disconnected
        # 3. Or all clusters under this domain have been deleted
        if domain_id not in self.domain_pool:
            self.logger.info(f"✅ NodeManager: Domain pool {domain_id} not found, should be removed")
            return True
            
        remaining_connections = self.domain_pool[domain_id]
        self.logger.info(f"🔍 NodeManager: Domain pool {domain_id} has {len(remaining_connections)} remaining connections")
        
        if not remaining_connections:
            self.logger.info(f"✅ NodeManager: Domain pool {domain_id} is empty, should be removed")
            return True
            
        # Check if there are still related clusters
        active_clusters = []
        for conn in remaining_connections:
            if conn.cluster_id and conn.cluster_id in self.cluster_pool:
                active_clusters.append(conn.cluster_id)
        
        self.logger.info(f"🔍 NodeManager: Domain pool {domain_id} has active clusters: {active_clusters}")
        
        if not active_clusters:
            self.logger.info(f"✅ NodeManager: Domain pool {domain_id} has no active clusters, should be removed")
            return True
        else:
            self.logger.info(f"📊 NodeManager: Domain pool {domain_id} has active clusters, keeping pool")
            
        return False
    
    # ===================== WebSocket Communication =====================
    
    async def send_to_c_client(self, connection: ClientConnection, command: Dict[str, Any]) -> Dict[str, Any]:
        """Send command to C-Client and wait for response"""
        try:
            request_id = str(uuid.uuid4())
            command['request_id'] = request_id
            
            # Create future for response
            future = asyncio.Future()
            self.pending_requests[request_id] = future
            
            # Send command
            await connection.websocket.send(json.dumps(command))
            self.logger.info(f"Sent command {command['type']} to C-Client with request_id: {request_id}")
            
            # Wait for response with timeout
            try:
                self.logger.info(f"⏳ Waiting for response (timeout: 30s)...")
                response = await asyncio.wait_for(future, timeout=30.0)
                self.logger.info(f"✅ Received response for {command['type']}")
                self.logger.info(f"📋 Response data: {response}")
                # Clean up on success
                if request_id in self.pending_requests:
                    del self.pending_requests[request_id]
                return response
            except asyncio.TimeoutError:
                self.logger.error(f"❌ Timeout waiting for response to {command['type']} (request_id: {request_id})")
                self.logger.error(f"   No response received after 30 seconds")
                self.logger.error(f"   Keeping request_id in pending_requests for late response handling")
                # Don't delete yet - allow late response to be processed
                return {"success": False, "error": "Timeout"}
                    
        except ConnectionClosed:
            self.logger.error("Connection closed while sending command")
            return {"success": False, "error": "Connection closed"}
        except Exception as e:
            self.logger.error(f"Error sending command: {e}")
            return {"success": False, "error": str(e)}
    
    async def handle_c_client_response(self, connection: ClientConnection, response: Dict[str, Any]):
        """Handle response from C-Client"""
        request_id = response.get('request_id')
        command_type = response.get('command_type')
        
        self.logger.info(f"📥 NODEMANAGER: handle_c_client_response() CALLED")
        self.logger.info(f"   Request ID: {request_id}")
        self.logger.info(f"   Command type: {command_type}")
        self.logger.info(f"   Success: {response.get('success')}")
        
        if request_id and request_id in self.pending_requests:
            future = self.pending_requests[request_id]
            if not future.done():
                self.logger.info(f"✅ Setting result for pending request {request_id}")
                future.set_result(response)
            else:
                self.logger.warning(f"⚠️ Future for request {request_id} already done (likely timed out)")
                self.logger.info(f"   Processing late response manually...")
                
                # Handle late response - process the result even though timeout occurred
                if response.get('success') and command_type:
                    await self._process_late_response(connection, command_type, response)
            
            # Clean up after handling
            del self.pending_requests[request_id]
            self.logger.info(f"✅ Cleaned up request_id: {request_id}")
        else:
            self.logger.warning(f"⚠️ No pending request found for request_id: {request_id}")
    
    async def _process_late_response(self, connection: ClientConnection, command_type: str, response: Dict[str, Any]):
        """Process a late response that arrived after timeout"""
        try:
            self.logger.info(f"🔄 PROCESSING LATE RESPONSE for {command_type}")
            data = response.get('data', {})
            
            if command_type == 'new_domain_node':
                domain_id = data.get('domain_id')
                if domain_id:
                    self.logger.info(f"   Late response: domain_id = {domain_id}")
                    connection.domain_id = domain_id
                    # Continue with cluster creation
                    self.logger.info(f"   Continuing to create cluster...")
                    await self.new_cluster_node(connection, domain_id)
                    
            elif command_type == 'new_cluster_node':
                cluster_id = data.get('cluster_id')
                if cluster_id:
                    self.logger.info(f"   Late response: cluster_id = {cluster_id}")
                    connection.cluster_id = cluster_id
                    # Continue with channel creation
                    self.logger.info(f"   Continuing to create channel...")
                    await self.new_channel_node(connection, connection.domain_id, cluster_id)
                    
            elif command_type == 'new_channel_node':
                channel_id = data.get('channel_id')
                if channel_id:
                    self.logger.info(f"   Late response: channel_id = {channel_id}")
                    connection.channel_id = channel_id
                    # Add to channel pool
                    if connection.is_channel_main_node:
                        if channel_id not in self.channel_pool:
                            self.channel_pool[channel_id] = []
                        self.channel_pool[channel_id].append(connection)
                        self.logger.info(f"   ✅ Added to channel_pool[{channel_id}]")
                    self.logger.info(f"   ✅ Full hierarchy completed via late response!")
                    
            self.logger.info(f"✅ Late response processed successfully")
        except Exception as e:
            self.logger.error(f"❌ Error processing late response: {e}")
    
    # ===================== Count Peers Methods =====================
    
    async def count_peers(self, connection: ClientConnection, domain_id: Optional[str] = None, 
                         cluster_id: Optional[str] = None, channel_id: Optional[str] = None) -> int:
        """Count peers at specified level"""
        try:
            command = {
                "type": "count_peers_amount",
                "data": {
                    "domain_id": domain_id,
                    "cluster_id": cluster_id,
                    "channel_id": channel_id
                }
            }
            
            response = await self.send_to_c_client(connection, command)
            
            if response.get("success"):
                return response.get("data", {}).get("count", 0)
            else:
                self.logger.error(f"Failed to count peers: {response.get('error')}")
                return 0
                
        except Exception as e:
            self.logger.error(f"Error in count_peers: {e}")
            return 0
    
    # ===================== Assign To Methods =====================
    
    async def assign_to_channel(self, connection: ClientConnection, channel_id: str, 
                               channel_node_id: str) -> bool:
        """Assign C-Client to channel"""
        try:
            # Get channel pool object (should exist even if main node is offline)
            channel_connections = self.channel_pool.get(channel_id, [])
            
            # Try to count peers through ANY connection in the pool (main node or regular node)
            node_count = 0
            if channel_connections:
                self.logger.info(f"📊 Channel pool has {len(channel_connections)} connection(s)")
                self.logger.info(f"   → Attempting to count peers through available connections...")
                
                # Try to count through any available connection
                count_success = False
                for conn in channel_connections:
                    try:
                        node_count = await self.count_peers(conn, None, None, None)
                        self.logger.info(f"✅ Successfully counted peers through node {conn.node_id}: {node_count} nodes")
                        count_success = True
                        break
                    except Exception as e:
                        self.logger.warning(f"⚠️ Failed to count through node {conn.node_id}: {e}")
                        continue
                
                if count_success:
                    if node_count >= 1000:
                        self.logger.info(f"❌ Channel {channel_id} is full ({node_count} nodes)")
                        return False
                    else:
                        self.logger.info(f"✅ Channel {channel_id} has capacity ({node_count} < 1000)")
                else:
                    self.logger.warning(f"⚠️ All connections failed to count peers, proceeding with assignment anyway")
            else:
                self.logger.info(f"⚠️ Channel pool {channel_id} is empty (no connections)")
                self.logger.info(f"   → Skipping peer count, directly assigning (assuming available)")
            
            # Send assignToChannel command
            command = {
                "type": "assign_to_channel",
                "data": {
                    "domain_id": connection.domain_id,    # Add domain_id
                    "cluster_id": connection.cluster_id,  # Add cluster_id
                    "channel_id": channel_id,
                    "node_id": connection.node_id
                }
            }
            
            response = await self.send_to_c_client(connection, command)
            
            if response.get("success"):
                # Add to channel pool
                self.add_to_channel_pool(channel_id, connection)
                
                # Notify all channel nodes about new peer
                await self.add_new_node_to_peers(
                    response.get("data", {}).get("domain_id"),
                    response.get("data", {}).get("cluster_id"),
                    channel_id,
                    connection.node_id
                )
                
                self.logger.info(f"✅ Successfully assigned {connection.node_id} to channel {channel_id}")
                return True
            else:
                self.logger.error(f"❌ Failed to assign to channel: {response.get('error')}")
                return False
                
        except Exception as e:
            self.logger.error(f"❌ Error in assign_to_channel: {e}")
            return False
    
    async def assign_to_cluster(self, connection: ClientConnection, cluster_id: str, 
                               cluster_node_id: str) -> bool:
        """Assign C-Client to cluster"""
        try:
            # Get cluster pool object (should exist even if main node is offline)
            cluster_connections = self.cluster_pool.get(cluster_id, [])
            
            # Try to count peers through ANY connection in the pool (main node or regular node)
            channel_count = 0
            if cluster_connections:
                self.logger.info(f"📊 Cluster pool has {len(cluster_connections)} connection(s)")
                self.logger.info(f"   → Attempting to count peers through available connections...")
                
                # Try to count through any available connection
                count_success = False
                for conn in cluster_connections:
                    try:
                        channel_count = await self.count_peers(conn, None, cluster_id, None)
                        self.logger.info(f"✅ Successfully counted peers through node {conn.node_id}: {channel_count} channels")
                        count_success = True
                        break
                    except Exception as e:
                        self.logger.warning(f"⚠️ Failed to count through node {conn.node_id}: {e}")
                        continue
                
                if count_success:
                    if channel_count >= 1000:
                        self.logger.info(f"❌ Cluster {cluster_id} is full ({channel_count} channels)")
                        return False
                    else:
                        self.logger.info(f"✅ Cluster {cluster_id} has capacity ({channel_count} < 1000)")
                else:
                    self.logger.warning(f"⚠️ All connections failed to count peers, proceeding with assignment anyway")
            else:
                self.logger.info(f"⚠️ Cluster pool {cluster_id} is empty (no connections)")
                self.logger.info(f"   → Skipping peer count, directly assigning (assuming available)")
            
            # Send assignToCluster command
            command = {
                "type": "assign_to_cluster",
                "data": {
                    "domain_id": connection.domain_id,  # Add domain_id
                    "cluster_id": cluster_id,
                    "node_id": connection.node_id
                }
            }
            
            response = await self.send_to_c_client(connection, command)
            
            if response.get("success"):
                # Add to cluster pool
                self.add_to_cluster_pool(cluster_id, connection)
                
                # Try to assign to existing channel - try ALL channels in the cluster
                channel_assigned = False
                for channel_connection in self.cluster_pool.get(cluster_id, []):
                    if channel_connection.channel_id:
                        self.logger.info(f"🔍 Trying to assign to existing channel: {channel_connection.channel_id}")
                        if await self.assign_to_channel(connection, channel_connection.channel_id, 
                                                       channel_connection.node_id):
                            self.logger.info(f"✅ Successfully assigned to existing channel: {channel_connection.channel_id}")
                            channel_assigned = True
                            break
                        else:
                            self.logger.warning(f"⚠️ Failed to assign to channel {channel_connection.channel_id}, trying next...")
                
                # Only create new channel if NO existing channels were available
                if not channel_assigned:
                    self.logger.info(f"📍 No available channels found, creating new channel for cluster {cluster_id}")
                    # Use connection's domain_id instead of response data
                    domain_id = connection.domain_id
                    if domain_id:
                        await self.new_channel_node(connection, domain_id, cluster_id)
                        # Assign to own channel
                        if connection.channel_id:
                            return await self.assign_to_channel(connection, connection.channel_id, 
                                                              connection.node_id)
                
                self.logger.info(f"✅ Successfully assigned {connection.node_id} to cluster {cluster_id}")
                return True
            else:
                self.logger.error(f"❌ Failed to assign to cluster: {response.get('error')}")
                return False
                
        except Exception as e:
            self.logger.error(f"❌ Error in assign_to_cluster: {e}")
            return False
    
    async def assign_to_domain(self, connection: ClientConnection, domain_id: str, 
                              domain_node_id: str) -> bool:
        """Assign C-Client to domain"""
        try:
            # Get domain pool object (should exist even if main node is offline)
            domain_connections = self.domain_pool.get(domain_id, [])
            
            # Try to count peers through ANY connection in the pool (main node or regular node)
            cluster_count = 0
            if domain_connections:
                self.logger.info(f"📊 Domain pool has {len(domain_connections)} connection(s)")
                self.logger.info(f"   → Attempting to count peers through available connections...")
                
                # Try to count through any available connection
                count_success = False
                for conn in domain_connections:
                    try:
                        cluster_count = await self.count_peers(conn, domain_id, None, None)
                        self.logger.info(f"✅ Successfully counted peers through node {conn.node_id}: {cluster_count} clusters")
                        count_success = True
                        break
                    except Exception as e:
                        self.logger.warning(f"⚠️ Failed to count through node {conn.node_id}: {e}")
                        continue
                
                if count_success:
                    if cluster_count >= 1000:
                        self.logger.info(f"❌ Domain {domain_id} is full ({cluster_count} clusters)")
                        return False
                    else:
                        self.logger.info(f"✅ Domain {domain_id} has capacity ({cluster_count} < 1000)")
                else:
                    self.logger.warning(f"⚠️ All connections failed to count peers, proceeding with assignment anyway")
            else:
                self.logger.info(f"⚠️ Domain pool {domain_id} is empty (no connections)")
                self.logger.info(f"   → Skipping peer count, directly assigning (assuming available)")
            
            # Send assignToDomain command
            command = {
                "type": "assign_to_domain",
                "data": {
                    "domain_id": domain_id,
                    "node_id": connection.node_id
                }
            }
            
            response = await self.send_to_c_client(connection, command)
            
            if response.get("success"):
                # Add to domain pool
                self.add_to_domain_pool(domain_id, connection)
                
                # Try to assign to existing cluster - try ALL clusters in the domain
                cluster_assigned = False
                for cluster_connection in self.domain_pool.get(domain_id, []):
                    if cluster_connection.cluster_id:
                        self.logger.info(f"🔍 Trying to assign to existing cluster: {cluster_connection.cluster_id}")
                        if await self.assign_to_cluster(connection, cluster_connection.cluster_id, 
                                                       cluster_connection.node_id):
                            self.logger.info(f"✅ Successfully assigned to existing cluster: {cluster_connection.cluster_id}")
                            cluster_assigned = True
                            break
                        else:
                            self.logger.warning(f"⚠️ Failed to assign to cluster {cluster_connection.cluster_id}, trying next...")
                
                # Only create new cluster if NO existing clusters were available
                if not cluster_assigned:
                    self.logger.info(f"📍 No available clusters found, creating new cluster for domain {domain_id}")
                    await self.new_cluster_node(connection, domain_id)
                    # Assign to own cluster
                    if connection.cluster_id:
                        return await self.assign_to_cluster(connection, connection.cluster_id, 
                                                          connection.node_id)
                
                self.logger.info(f"✅ Successfully assigned {connection.node_id} to domain {domain_id}")
                return True
            else:
                self.logger.error(f"❌ Failed to assign to domain: {response.get('error')}")
                return False
                
        except Exception as e:
            self.logger.error(f"❌ Error in assign_to_domain: {e}")
            return False
    
    # ===================== New Node Methods =====================
    
    async def new_channel_node(self, connection: ClientConnection, domain_id: str, 
                              cluster_id: str) -> bool:
        """Create new channel node (final level)"""
        try:
            self.logger.info(f"🏗️ Creating new channel node for {connection.node_id} in cluster {cluster_id}")
            
            command = {
                "type": "new_channel_node",
                "data": {
                    "domain_id": domain_id,
                    "cluster_id": cluster_id
                }
            }
            
            response = await self.send_to_c_client(connection, command)
            
            if not response.get("success"):
                self.logger.error(f"Failed to create channel node: {response.get('error')}")
                return False
            
            # Get channel_id from response
            channel_id = response.get("data", {}).get("channel_id")
            if not channel_id:
                self.logger.error("No channel_id in response")
                return False
            
            # Update connection
            connection.channel_id = channel_id
            connection.is_channel_main_node = True
            
            # Add to channel pool
            self.add_to_channel_pool(channel_id, connection)
            self.logger.info(f"✅ Created channel node: {channel_id}")
            self.logger.info(f"🎉 Full node hierarchy completed for {connection.node_id}")
            self.logger.info(f"   Domain: {domain_id}")
            self.logger.info(f"   Cluster: {cluster_id}")
            self.logger.info(f"   Channel: {channel_id}")
            
            return True
                
        except Exception as e:
            self.logger.error(f"Error in new_channel_node: {e}")
            return False
    
    async def new_cluster_node(self, connection: ClientConnection, domain_id: str) -> bool:
        """Create new cluster node and complete hierarchy"""
        try:
            self.logger.info(f"🏗️ Creating new cluster node for {connection.node_id} in domain {domain_id}")
            
            # Step 1: Create cluster
            command = {
                "type": "new_cluster_node",
                "data": {
                    "domain_id": domain_id
                }
            }
            
            response = await self.send_to_c_client(connection, command)
            
            if not response.get("success"):
                self.logger.error(f"Failed to create cluster node: {response.get('error')}")
                return False
            
            # Get cluster_id from response
            cluster_id = response.get("data", {}).get("cluster_id")
            if not cluster_id:
                self.logger.error("No cluster_id in response")
                return False
            
            # Update connection
            connection.cluster_id = cluster_id
            connection.is_cluster_main_node = True
            
            # Add to cluster pool
            self.add_to_cluster_pool(cluster_id, connection)
            self.logger.info(f"✅ Created cluster node: {cluster_id}")
            
            # Step 2: Create channel
            self.logger.info(f"🏗️ Creating channel for cluster {cluster_id}")
            channel_result = await self.new_channel_node(connection, domain_id, cluster_id)
            
            if not channel_result:
                self.logger.warning("Failed to create channel, but cluster created successfully")
                return True  # Cluster is created, so return True
            
            self.logger.info(f"✅ Successfully created cluster node with full hierarchy: {cluster_id}")
            return True
                
        except Exception as e:
            self.logger.error(f"Error in new_cluster_node: {e}")
            return False
    
    async def new_domain_node(self, connection: ClientConnection) -> bool:
        """Create new domain node and complete hierarchy"""
        try:
            self.logger.info(f"🏗️ Creating new domain node for {connection.node_id}")
            
            # Step 1: Create domain
            command = {
                "type": "new_domain_node",
                "data": {}
            }
            
            response = await self.send_to_c_client(connection, command)
            
            if not response.get("success"):
                self.logger.error(f"Failed to create domain node: {response.get('error')}")
                return False
            
            # Get domain_id from response
            domain_id = response.get("data", {}).get("domain_id")
            if not domain_id:
                self.logger.error("No domain_id in response")
                return False
            
            # Update connection
            connection.domain_id = domain_id
            connection.is_domain_main_node = True
            
            # Add to domain pool
            self.add_to_domain_pool(domain_id, connection)
            self.logger.info(f"✅ Created domain node: {domain_id}")
            
            # Step 2: Create cluster
            self.logger.info(f"🏗️ Creating cluster for domain {domain_id}")
            cluster_result = await self.new_cluster_node(connection, domain_id)
            
            if not cluster_result:
                self.logger.warning("Failed to create cluster, but domain created successfully")
                return True  # Domain is created, so return True
            
            self.logger.info(f"✅ Successfully created domain node with full hierarchy: {domain_id}")
            return True
                
        except Exception as e:
            self.logger.error(f"Error in new_domain_node: {e}")
            return False
    
    # ===================== Add Peers Methods =====================
    
    async def add_new_node_to_peers(self, domain_id: str, cluster_id: str, 
                                   channel_id: str, node_id: str):
        """Notify all nodes in channel about new peer"""
        try:
            if channel_id not in self.channel_pool:
                self.logger.warning(f"Channel pool {channel_id} not found")
                return
            
            command = {
                "type": "add_new_node_to_peers",
                "data": {
                    "domain_id": domain_id,
                    "cluster_id": cluster_id,
                    "channel_id": channel_id,
                    "node_id": node_id
                }
            }
            
            # Send to all connections in channel
            tasks = []
            for connection in self.channel_pool[channel_id]:
                task = self.send_to_c_client(connection, command)
                tasks.append(task)
            
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
                self.logger.info(f"Notified {len(tasks)} nodes in channel {channel_id} about new peer {node_id}")
                
        except Exception as e:
            self.logger.error(f"Error in add_new_node_to_peers: {e}")
    
    async def add_new_channel_to_peers(self, domain_id: str, cluster_id: str, 
                                      channel_id: str, node_id: str):
        """Notify all nodes in cluster about new channel"""
        try:
            if cluster_id not in self.cluster_pool:
                self.logger.warning(f"Cluster pool {cluster_id} not found")
                return
            
            command = {
                "type": "add_new_channel_to_peers",
                "data": {
                    "domain_id": domain_id,
                    "cluster_id": cluster_id,
                    "channel_id": channel_id,
                    "node_id": node_id
                }
            }
            
            # Send to all connections in cluster
            tasks = []
            for connection in self.cluster_pool[cluster_id]:
                task = self.send_to_c_client(connection, command)
                tasks.append(task)
            
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
                self.logger.info(f"Notified {len(tasks)} nodes in cluster {cluster_id} about new channel {channel_id}")
                
        except Exception as e:
            self.logger.error(f"Error in add_new_channel_to_peers: {e}")
    
    async def add_new_cluster_to_peers(self, domain_id: str, cluster_id: str, node_id: str):
        """Notify all nodes in domain about new cluster"""
        try:
            if domain_id not in self.domain_pool:
                self.logger.warning(f"Domain pool {domain_id} not found")
                return
            
            command = {
                "type": "add_new_cluster_to_peers",
                "data": {
                    "domain_id": domain_id,
                    "cluster_id": cluster_id,
                    "node_id": node_id
                }
            }
            
            # Send to all connections in domain
            tasks = []
            for connection in self.domain_pool[domain_id]:
                task = self.send_to_c_client(connection, command)
                tasks.append(task)
            
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
                self.logger.info(f"Notified {len(tasks)} nodes in domain {domain_id} about new cluster {cluster_id}")
                
        except Exception as e:
            self.logger.error(f"Error in add_new_cluster_to_peers: {e}")
    
    async def add_new_domain_to_peers(self, domain_id: str, node_id: str):
        """Notify all domain nodes about new domain"""
        try:
            command = {
                "type": "add_new_domain_to_peers",
                "data": {
                    "domain_id": domain_id,
                    "node_id": node_id
                }
            }
            
            # Send to all domain connections
            tasks = []
            for connections in self.domain_pool.values():
                for connection in connections:
                    task = self.send_to_c_client(connection, command)
                    tasks.append(task)
            
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
                self.logger.info(f"Notified {len(tasks)} domain nodes about new domain {domain_id}")
                
        except Exception as e:
            self.logger.error(f"Error in add_new_domain_to_peers: {e}")
    
    # ===================== Utility Methods =====================
    
    def get_pool_stats(self) -> Dict[str, Any]:
        """Get statistics about connection pools"""
        return {
            "domains": len(self.domain_pool),
            "clusters": len(self.cluster_pool),
            "channels": len(self.channel_pool),
            "total_connections": sum(
                len(connections) 
                for connections in self.domain_pool.values()
            ),
            "domain_details": {
                domain_id: len(connections) 
                for domain_id, connections in self.domain_pool.items()
            },
            "cluster_details": {
                cluster_id: len(connections) 
                for cluster_id, connections in self.cluster_pool.items()
            },
            "channel_details": {
                channel_id: len(connections) 
                for channel_id, connections in self.channel_pool.items()
            }
        }
    
    def get_main_node_ids(self, domain_id: str = None, cluster_id: str = None, channel_id: str = None) -> Dict[str, str]:
        """
        Get main node IDs for domain, cluster, and channel
        Returns the first valid connection's node_id from each pool
        
        Args:
            domain_id: Domain ID to query (optional)
            cluster_id: Cluster ID to query (optional)
            channel_id: Channel ID to query (optional)
            
        Returns:
            Dict with domain_main_node_id, cluster_main_node_id, channel_main_node_id
        """
        try:
            self.logger.info("=" * 80)
            self.logger.info("🔍 NODEMANAGER: get_main_node_ids() CALLED")
            self.logger.info(f"   Query params: domain_id={domain_id}, cluster_id={cluster_id}, channel_id={channel_id}")
            
            result = {
                'domain_main_node_id': None,
                'cluster_main_node_id': None,
                'channel_main_node_id': None
            }
            
            # Get domain main node
            if domain_id and domain_id in self.domain_pool:
                domain_connections = self.domain_pool[domain_id]
                # Find first valid connection that is marked as domain main
                for conn in domain_connections:
                    if self._is_websocket_valid(conn.websocket) and conn.is_domain_main_node:
                        result['domain_main_node_id'] = conn.node_id
                        self.logger.info(f"✅ Found domain main node: {conn.node_id}")
                        break
                
                if not result['domain_main_node_id']:
                    self.logger.info(f"⚠️ No domain main node found in domain {domain_id}")
            else:
                self.logger.info(f"⚠️ Domain {domain_id} not found in domain_pool")
            
            # Get cluster main node
            if cluster_id and cluster_id in self.cluster_pool:
                cluster_connections = self.cluster_pool[cluster_id]
                # Find first valid connection that is marked as cluster main
                for conn in cluster_connections:
                    if self._is_websocket_valid(conn.websocket) and conn.is_cluster_main_node:
                        result['cluster_main_node_id'] = conn.node_id
                        self.logger.info(f"✅ Found cluster main node: {conn.node_id}")
                        break
                
                if not result['cluster_main_node_id']:
                    self.logger.info(f"⚠️ No cluster main node found in cluster {cluster_id}")
            else:
                self.logger.info(f"⚠️ Cluster {cluster_id} not found in cluster_pool")
            
            # Get channel main node
            if channel_id and channel_id in self.channel_pool:
                channel_connections = self.channel_pool[channel_id]
                # Find first valid connection that is marked as channel main
                for conn in channel_connections:
                    if self._is_websocket_valid(conn.websocket) and conn.is_channel_main_node:
                        result['channel_main_node_id'] = conn.node_id
                        self.logger.info(f"✅ Found channel main node: {conn.node_id}")
                        break
                
                if not result['channel_main_node_id']:
                    self.logger.info(f"⚠️ No channel main node found in channel {channel_id}")
            else:
                self.logger.info(f"⚠️ Channel {channel_id} not found in channel_pool")
            
            self.logger.info(f"🔍 Main node IDs result: {result}")
            self.logger.info("=" * 80)
            
            return result
            
        except Exception as e:
            self.logger.error(f"❌ Error getting main node IDs: {e}")
            self.logger.error(f"Traceback: {traceback.format_exc()}")
            return {
                'domain_main_node_id': None,
                'cluster_main_node_id': None,
                'channel_main_node_id': None
            }
    
    def get_channel_nodes(self, channel_id: str) -> List[str]:
        """
        Get all node IDs in a specific channel (only valid connections)
        
        Args:
            channel_id: Channel ID to query
            
        Returns:
            List of node IDs in the channel (excluding closed/invalid connections)
        """
        try:
            if channel_id not in self.channel_pool:
                self.logger.info(f"No nodes found in channel {channel_id}")
                return []
            
            channel_connections = self.channel_pool[channel_id]
            
            # Filter out invalid/closed connections
            valid_connections = []
            invalid_connections = []
            
            for conn in channel_connections:
                if self._is_websocket_valid(conn.websocket):
                    valid_connections.append(conn)
                else:
                    invalid_connections.append(conn)
                    self.logger.debug(f"🔍 NodeManager: Filtering out invalid connection for node {conn.node_id}")
            
            # Log invalid connections found
            if invalid_connections:
                self.logger.info(f"🔍 NodeManager: Found {len(invalid_connections)} invalid connections in channel {channel_id}")
                for conn in invalid_connections:
                    self.logger.info(f"🔍 NodeManager: Invalid connection - node_id: {conn.node_id}, user_id: {conn.user_id}")
            
            # Get node IDs from valid connections only
            node_ids = [conn.node_id for conn in valid_connections]
            
            self.logger.info(f"Found {len(node_ids)} valid nodes in channel {channel_id}: {node_ids}")
            if invalid_connections:
                self.logger.info(f"Filtered out {len(invalid_connections)} invalid connections")
            
            return node_ids
            
        except Exception as e:
            self.logger.error(f"Error getting channel nodes: {e}")
            return []
    
    def _is_websocket_valid(self, websocket) -> bool:
        """Check if a WebSocket connection is still valid using the same logic as WebSocketClient"""
        try:
            # Check if connection was marked as closed by logout
            if hasattr(websocket, '_closed_by_logout') and websocket._closed_by_logout:
                self.logger.debug(f"🔍 NodeManager: Connection marked as closed by logout")
                return False
            
            # Check WebSocket closed attribute
            if hasattr(websocket, 'closed') and websocket.closed:
                self.logger.debug(f"🔍 NodeManager: Connection is closed (closed=True)")
                return False
            
            # Check connection state - use multiple methods for reliability
            connection_valid = True
            
            # Method 1: Check websockets state attribute
            if hasattr(websocket, 'state'):
                state_value = websocket.state
                state_name = websocket.state.name if hasattr(websocket.state, 'name') else str(websocket.state)
                
                # Check state value (3 = CLOSED, 2 = CLOSING)
                if state_value in [2, 3] or state_name in ['CLOSED', 'CLOSING']:
                    self.logger.debug(f"🔍 NodeManager: Connection is in {state_name} state (value: {state_value})")
                    connection_valid = False
            
            # Method 2: Check close_code
            if hasattr(websocket, 'close_code') and websocket.close_code is not None:
                self.logger.debug(f"🔍 NodeManager: Connection has close_code {websocket.close_code}")
                connection_valid = False
            
            # Method 3: Try to access the websocket object
            try:
                # This is a lightweight check - just accessing the websocket object
                # without actually sending data
                if hasattr(websocket, '_closed') and websocket._closed:
                    self.logger.debug(f"🔍 NodeManager: Connection is marked as _closed")
                    connection_valid = False
            except Exception:
                self.logger.debug(f"🔍 NodeManager: Connection appears to be invalid (exception during ping test)")
                connection_valid = False
            
            if connection_valid:
                self.logger.debug(f"🔍 NodeManager: Connection appears to be valid")
            else:
                self.logger.debug(f"🔍 NodeManager: Connection is invalid")
            
            return connection_valid
            
        except Exception as e:
            self.logger.debug(f"🔍 NodeManager: Error checking connection validity: {e}")
            return False
    
    async def cleanup_disconnected_connections(self):
        """Clean up disconnected connections from pools"""
        disconnected_connections = []
        
        # Check all connections in all pools
        for pool_name, pool in [
            ('domain_pool', self.domain_pool),
            ('cluster_pool', self.cluster_pool),
            ('channel_pool', self.channel_pool)
        ]:
            for pool_id, connections in pool.items():
                for connection in connections:
                    if not self._is_websocket_valid(connection.websocket):
                        disconnected_connections.append(connection)
                        self.logger.info(f"🔧 NodeManager: Found invalid connection in {pool_name}[{pool_id}]: node_id={connection.node_id}")
        
        # Remove disconnected connections
        if disconnected_connections:
            self.logger.info(f"🔧 NodeManager: Cleaning up {len(disconnected_connections)} invalid connections")
            for connection in disconnected_connections:
                self.remove_connection(connection)
            self.logger.info(f"🔧 NodeManager: Cleanup completed")
        else:
            self.logger.info(f"🔧 NodeManager: No invalid connections found")
    
    def get_valid_connections_count(self) -> Dict[str, int]:
        """Get count of valid connections in each pool"""
        try:
            valid_counts = {
                'domains': 0,
                'clusters': 0,
                'channels': 0,
                'total_valid': 0,
                'total_invalid': 0
            }
            
            # Check domain pool
            for connections in self.domain_pool.values():
                for conn in connections:
                    if self._is_websocket_valid(conn.websocket):
                        valid_counts['domains'] += 1
                        valid_counts['total_valid'] += 1
                    else:
                        valid_counts['total_invalid'] += 1
            
            # Check cluster pool
            for connections in self.cluster_pool.values():
                for conn in connections:
                    if self._is_websocket_valid(conn.websocket):
                        valid_counts['clusters'] += 1
                        valid_counts['total_valid'] += 1
                    else:
                        valid_counts['total_invalid'] += 1
            
            # Check channel pool
            for connections in self.channel_pool.values():
                for conn in connections:
                    if self._is_websocket_valid(conn.websocket):
                        valid_counts['channels'] += 1
                        valid_counts['total_valid'] += 1
                    else:
                        valid_counts['total_invalid'] += 1
            
            return valid_counts
            
        except Exception as e:
            self.logger.error(f"Error getting valid connections count: {e}")
            return {'error': str(e)}
            self.logger.info(f"Removed disconnected connection: {connection.node_id}")
        
        return len(disconnected_connections)
