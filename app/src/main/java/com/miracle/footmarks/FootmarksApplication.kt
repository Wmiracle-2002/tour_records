package com.miracle.footmarks

import android.app.Application
import com.miracle.footmarks.data.local.util.DatabaseInitializer
import dagger.hilt.android.HiltAndroidApp
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import javax.inject.Inject

@HiltAndroidApp
class FootmarksApplication : Application() {

    @Inject
    lateinit var databaseInitializer: DatabaseInitializer

    private val applicationScope = CoroutineScope(SupervisorJob() + Dispatchers.IO)

    override fun onCreate() {
        super.onCreate()

        // 初始化城市数据
        applicationScope.launch {
            databaseInitializer.initializeCities()
        }
    }
}
