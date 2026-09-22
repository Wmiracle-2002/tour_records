package com.miracle.footmarks.ui.navigation

import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.DateRange
import androidx.compose.material.icons.filled.Person
import androidx.compose.material.icons.filled.Star
import androidx.compose.material3.*
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.unit.dp
import androidx.compose.ui.res.stringResource
import androidx.navigation.NavDestination.Companion.hierarchy
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.NavHostController
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.navArgument
import androidx.hilt.navigation.compose.hiltViewModel
import com.miracle.footmarks.R
import com.miracle.footmarks.ui.screen.addrecord.AddRecordScreen
import com.miracle.footmarks.ui.screen.editrecord.EditRecordScreen
import com.miracle.footmarks.ui.screen.profile.ProfileScreen
import com.miracle.footmarks.ui.screen.profile.LoginScreen
import com.miracle.footmarks.ui.screen.profile.ProfileViewModel
import com.miracle.footmarks.ui.screen.recorddetail.RecordDetailScreen
import com.miracle.footmarks.ui.screen.records.RecordsScreen
import com.miracle.footmarks.ui.screen.smartplanning.SmartPlanningScreen
import com.miracle.footmarks.ui.screen.tripdetail.TripDetailScreen

data class BottomNavItem(
    val route: String,
    val icon: ImageVector,
    val label: Int
)

val bottomNavItems = listOf(
    BottomNavItem(Screen.Records.route, Icons.Default.DateRange, R.string.nav_records),
    BottomNavItem(Screen.SmartPlanning.route, Icons.Default.Star, R.string.nav_smart_planning),
    BottomNavItem(Screen.Profile.route, Icons.Default.Person, R.string.nav_profile)
)

@Composable
fun MainBottomBar(
    navController: NavHostController,
    modifier: Modifier = Modifier
) {
    NavigationBar(
        modifier = modifier,
        containerColor = MaterialTheme.colorScheme.surface,
        tonalElevation = 4.dp
    ) {
        val navBackStackEntry by navController.currentBackStackEntryAsState()
        val currentDestination = navBackStackEntry?.destination

        bottomNavItems.forEach { item ->
            NavigationBarItem(
                icon = { Icon(item.icon, contentDescription = null) },
                label = { Text(stringResource(item.label)) },
                selected = currentDestination?.hierarchy?.any { it.route == item.route } == true,
                colors = NavigationBarItemDefaults.colors(
                    selectedIconColor = MaterialTheme.colorScheme.primary,
                    selectedTextColor = MaterialTheme.colorScheme.primary,
                    indicatorColor = MaterialTheme.colorScheme.primaryContainer,
                    unselectedIconColor = MaterialTheme.colorScheme.onSurfaceVariant,
                    unselectedTextColor = MaterialTheme.colorScheme.onSurfaceVariant
                ),
                onClick = {
                    navController.navigate(item.route) {
                        popUpTo(navController.graph.findStartDestination().id) {
                            saveState = true
                        }
                        launchSingleTop = true
                        restoreState = true
                    }
                }
            )
        }
    }
}

@Composable
fun MainNavHost(
    navController: NavHostController,
    modifier: Modifier = Modifier
) {
    NavHost(
        navController = navController,
        startDestination = Screen.Records.route,
        modifier = modifier
    ) {
        composable(Screen.Records.route) {
            RecordsScreen(
                onTripClick = { tripId ->
                    navController.navigate(Screen.TripDetail.createRoute(tripId))
                },
                onRecordClick = { recordId ->
                    navController.navigate(Screen.RecordDetail.createRoute(recordId))
                },
                onAddClick = {
                    navController.navigate(Screen.AddRecord.createRoute())
                },
                onAddToTrip = { tripId ->
                    navController.navigate(Screen.AddRecord.createRoute(tripId))
                }
            )
        }

        composable(Screen.SmartPlanning.route) {
            SmartPlanningScreen()
        }

        composable(Screen.Profile.route) {
            ProfileScreen(
                onOpenLogin = { navController.navigate(Screen.Login.route) }
            )
        }

        composable(Screen.Login.route) {
            val profileEntry = navController.getBackStackEntry(Screen.Profile.route)
            val profileViewModel: ProfileViewModel = hiltViewModel(profileEntry)
            val cloudState by profileViewModel.cloudState.collectAsState()
            LoginScreen(
                state = cloudState,
                onLogin = profileViewModel::login,
                onLoggedIn = { navController.popBackStack() },
                onBack = { navController.popBackStack() }
            )
        }

        composable(
            route = Screen.AddRecord.route,
            arguments = listOf(
                navArgument("tripId") {
                    type = NavType.LongType
                    defaultValue = -1L
                }
            )
        ) {
            AddRecordScreen(
                onTripSaved = { tripId ->
                    navController.navigate(Screen.TripDetail.createRoute(tripId)) {
                        popUpTo(Screen.Records.route)
                    }
                },
                onRecordSaved = {
                    navController.popBackStack()
                },
                onCancel = {
                    navController.popBackStack()
                }
            )
        }

        composable(
            route = Screen.TripDetail.route,
            arguments = listOf(navArgument("tripId") { type = NavType.LongType })
        ) {
            TripDetailScreen(
                onBack = { navController.popBackStack() },
                onAddRecord = { tripId ->
                    navController.navigate(Screen.AddRecord.createRoute(tripId))
                },
                onRecordClick = { recordId ->
                    navController.navigate(Screen.RecordDetail.createRoute(recordId))
                }
            )
        }

        composable(
            route = Screen.EditRecord.route,
            arguments = listOf(navArgument("recordId") { type = NavType.LongType })
        ) {
            EditRecordScreen(
                onSaved = {
                    navController.popBackStack()
                },
                onCancel = {
                    navController.popBackStack()
                }
            )
        }

        composable(
            route = Screen.RecordDetail.route,
            arguments = listOf(navArgument("recordId") { type = NavType.LongType })
        ) {
            RecordDetailScreen(
                onBack = { navController.popBackStack() },
                onEdit = { recordId ->
                    navController.navigate(Screen.EditRecord.createRoute(recordId))
                }
            )
        }

        composable(
            route = Screen.CityDetail.route,
            arguments = listOf(navArgument("cityId") { type = NavType.LongType })
        ) {
            // CityDetailScreen - 后续实现
            Text("城市详情")
        }
    }
}
