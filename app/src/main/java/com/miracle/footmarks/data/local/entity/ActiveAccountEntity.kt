package com.miracle.footmarks.data.local.entity

import androidx.room.Entity
import androidx.room.PrimaryKey

@Entity(tableName = "active_account")
data class ActiveAccountEntity(@PrimaryKey val id: Int = 1, val userId: Long)

@Entity(tableName = "sync_cursors")
data class SyncCursorEntity(@PrimaryKey val userId: Long, val cursor: String)
