package com.miracle.footmarks.data.local.dao

import androidx.room.Dao
import androidx.room.Insert
import androidx.room.OnConflictStrategy
import androidx.room.Query
import com.miracle.footmarks.data.local.entity.ActiveAccountEntity
import com.miracle.footmarks.data.local.entity.SyncCursorEntity

@Dao
interface AccountDao {
    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun setActive(account: ActiveAccountEntity)

    @Query("SELECT userId FROM active_account WHERE id = 1")
    suspend fun activeUserId(): Long?

    @Insert(onConflict = OnConflictStrategy.REPLACE)
    suspend fun saveCursor(cursor: SyncCursorEntity)

    @Query("SELECT cursor FROM sync_cursors WHERE userId = :userId")
    suspend fun cursor(userId: Long): String?

    @Query("DELETE FROM sync_cursors WHERE userId = :userId")
    suspend fun deleteCursor(userId: Long)
}
