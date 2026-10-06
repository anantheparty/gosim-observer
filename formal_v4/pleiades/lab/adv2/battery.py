#!/usr/bin/env python3
"""Round-2 adversarial battery: NAME -> (type, seed, month shift, env). Twins: EA0 (A 8101 0), EB0 (B 8102 0),
EC0 (C 8103 0), ED0 (D 8104 0)."""
import json
A, B, C, D = ('A', 8101, 0), ('B', 8102, 0), ('C', 8103, 0), ('D', 8104, 0)
def off(a, z):
    return {'STRESS_ROWS': json.dumps([{'event_type': 'pointing_offset', 'trigger_mode': 'at_survey_start',
                                        'alt_offset_rad': f'{a:.8f}', 'az_offset_rad': f'{z:.8f}'}])}
def loss(when, s, e):
    return {'STRESS_ROWS': json.dumps([{'event_type': 'data_loss', 'trigger_mode': 'fixed_date', 'trigger_ref': when,
                                        'window_start_fraction': f'{s:.6f}', 'window_end_fraction': f'{e:.6f}',
                                        'window_max_fraction': '1.000000'}])}
ev = lambda d: {'EVENT_PATCH': json.dumps(d)}
scp = lambda d: {'SCORE_PATCH': json.dumps(d)}
W = {
    'ED0': (D, {}),
    # stress: pointing offsets far beyond the reference 0.002 rad (legal up to 0.1 rad) and massive data loss
    'JS1': (A, off(0.012, -0.010)), 'JS2': (A, off(0.025, 0.020)), 'JS3': (C, off(-0.030, 0.030)),
    'JS4': (D, off(0.012, 0.012)), 'JS5': (B, off(0.050, -0.040)),
    'JS6': (A, loss('2027-01-01T03:00:00Z', 0.0, 0.9)), 'JS7': (C, loss('2027-01-30T10:00:00Z', 0.3, 0.95)),
    # short functional checks of the offset search (5 nights)
    'JS2s': (A, dict(off(0.025, 0.020), WEIRD_NIGHTS='5')), 'JS3s': (C, dict(off(-0.030, 0.030), WEIRD_NIGHTS='5')),
    'JS5s': (B, dict(off(0.050, -0.040), WEIRD_NIGHTS='5')), 'JS4s': (D, dict(off(0.012, 0.012), WEIRD_NIGHTS='5')),
    'JS0s': (D, dict(off(-0.0015, 0.0012), WEIRD_NIGHTS='5')),
    # events
    'JE1': (A, ev({'terrain_obstruction.sector_count': [5, 7], 'terrain_obstruction.width_deg_range': [90.0, 160.0],
                   'terrain_obstruction.max_altitude_deg_range': [60.0, 80.0]})),
    'JE1b': (A, ev({'terrain_obstruction.max_altitude_deg_range': [50.0, 70.0]})),
    'JE1c': (A, ev({'terrain_obstruction.sector_count': [3, 5], 'terrain_obstruction.width_deg_range': [60.0, 120.0],
                    'terrain_obstruction.max_altitude_deg_range': [45.0, 65.0]})),
    'JE2': (A, ev({'weather_events.sector_width_deg_range': [150.0, 300.0],
                   'weather_events.sector_altitude_limit_deg_range': [75.0, 89.0],
                   'weather_events.conditions.cloudy.count': 40, 'weather_events.conditions.smoggy.count': 20,
                   'weather_events.conditions.rainy.count': 15})),
    'JE3': (A, ev({'instrument_fault.count': 10, 'instrument_fault.instrument_efficiency_multiplier_range': [0.85, 0.95]})),
    'JE4': (A, ev({'instrument_fault.count': 3, 'instrument_fault.instrument_efficiency_multiplier_range': [0.02, 0.1]})),
    'JE5': (A, ev({'earthquake.count': 8, 'earthquake.magnitude_range': [6.5, 8.5], 'earthquake.seeing_impact_coefficient': 0.5,
                   'earthquake.transparency_impact_coefficient': 0.5, 'earthquake.sky_quality_impact_coefficient': 0.5,
                   'earthquake.decay_nights': 10.0})),
    'JE6': (A, ev({'rocket_launch.count': 40, 'rocket_launch.duration_slots': [10, 30],
                   'rocket_launch.azimuth_sector_width_deg': [120.0, 200.0], 'rocket_launch.max_altitude_deg': [70.0, 88.0]})),
    'JE7': (A, ev({'publication.forecast_interval_days': 28, 'publication.forecast_horizon_days': 1})),
    'JE8': (A, ev({'survey.slot_seconds': 300})),
    'JE9': (A, ev({'survey.slot_seconds': 3600})),
    'JE10': (A, dict(ev({'survey.sun_altitude_limit_deg': -6.0}),
                     CAT_PATCH=json.dumps({'observability.sun_altitude_limit_deg': -6.0}))),
    'JE11': (A, ev({'quality.night_correlation': 0.2, 'quality.slot_correlation': 0.3,
                    'quality.seeing_arcsec.night_sigma': 0.4, 'quality.seeing_arcsec.slot_sigma': 0.2,
                    'quality.transparency.night_sigma': 0.15, 'quality.transparency.slot_sigma': 0.08,
                    'quality.sky_quality.night_sigma': 0.25, 'quality.sky_quality.slot_sigma': 0.1})),
    'JE12': (A, ev({'background_closure.start_probability_per_open_slot': 0.05,
                    'background_closure.reopen_probability_per_closed_slot': 0.1})),
    'JE13': (A, ev({'weather_events.conditions.cold_wave.count': 20, 'weather_events.conditions.cold_wave.transparency_multiplier': 0.4,
                    'weather_events.conditions.cold_wave.seeing_multiplier': 1.6,
                    'weather_events.conditions.cold_wave.sky_quality_multiplier': 0.5})),
    'JE14': (A, ev({'quality.instrument_efficiency.jitter_minimum': 0.5, 'quality.instrument_efficiency.jitter_maximum': 1.0,
                    'instrument_fault.count': 2})),
    # scoring
    'JC1': (A, scp({'required.penalty_per_missing': 3000, 'required.observed_factor_threshold': 0.9})),
    'JC2': (A, scp({'uniformity.weight': 30000.0, 'uniformity.ra_band_width_deg': 5.0})),
    'JC3': (A, dict(scp({'reporting.correct_reward': 2000, 'reporting.false_penalty': -100,
                         'reporting.false_report_free_allowance': 3}), **ev({'instrument_fault.count': 3}))),
    'JC4': (A, scp({'reporting.max_consecutive_reports': 1})),
    'JC5': (A, scp({'observation_requests.completion_factor_threshold': 1.0})),
    'JC6': (A, scp({'exposure_zero_point_seconds': 3600})),
    'JC7': (A, scp({'exposure_zero_point_seconds': 180})),
    'JC8': (A, scp({'airmass_exponent': 3.0})),
    'JC9': (A, scp({'program.bands.DARK': 0.95, 'program.bands.BRIGHT': 0.8, 'program.multipliers.DARK': 1.0,
                    'program.multipliers.BRIGHT': 0.6, 'program.multipliers.BACKUP': 0.25, 'program.mismatch_multiplier': 0.1})),
    'JC10': (A, scp({'program.mismatch_multiplier': 1.3})),
    'JC11': (A, scp({'lunar_model.maximum_penalty': 0.98, 'lunar_model.angular_decay_scale_deg': 90.0})),
    # fibres / exposures
    'JF1': (A, {'WEIRD_NFIB': '1'}), 'JF2': (A, {'WEIRD_NFIB': '400', 'WEIRD_AREA': '0.016'}),
    'JF3': (A, {'WEIRD_NFIB': '900'}), 'JF4': (A, {'WEIRD_GAP': '0.3'}),
    'JF5': (A, {'WEIRD_TMIN': '1200', 'WEIRD_TMAX': '1200'}), 'JF6': (A, {'WEIRD_TMIN': '1', 'WEIRD_TMAX': '120'}),
    'JF7': (A, {'WEIRD_TMIN': '3600', 'WEIRD_TMAX': '14400'}),
    # catalogue / site / season
    'JT1': (A, {'WEIRD_NT': '60'}), 'JT2': (A, {'WEIRD_LAT': '0.5', 'WEIRD_LON': '179.8'}),
    'JT3': (('A', 8101, 8), {'WEIRD_LAT': '-66'}), 'JT4': (A, {'WEIRD_NIGHTS': '3'}), 'JT5': (A, {'WEIRD_NIGHTS': '240'}),
    'JT6': (A, {'WEIRD_LAT': '45', 'CAT_PATCH': json.dumps({'footprint.n_components': 1, 'footprint.component_area_weights': [1.0],
                                                            'footprint.component_centers': [[0.0, 89.0]]})}),
    'JT7': (A, {'TARGET_EDIT': "r['feature_flux'] = '0.0' if rng.random() < 0.25 else r['feature_flux']\n"
                               "r['science_weight'] = '0.0' if rng.random() < 0.15 else r['science_weight']"}),
    'JT8': (A, {'TARGET_EDIT': "r['science_weight'] = str(float(r['science_weight']) * 60) if rng.random() < 0.01 else r['science_weight']"}),
    'JT9': (A, {'CAT_PATCH': json.dumps({'observability.minimum_altitude_deg': 75.0})}),
    'JT10': (A, {'CAT_PATCH': json.dumps({'observability.minimum_altitude_deg': 5.0})}),
    'JK1': (A, {'CAT_PATCH': json.dumps({'targets.required_fraction': 0.4})}),
    'JK2': (A, {'CAT_PATCH': json.dumps({'targets.clustered_fraction': 0.9, 'targets.n_cluster_centers': 30,
                                         'targets.cluster_sigma_deg': 0.2})}),
    'JK3': (A, {'CAT_PATCH': json.dumps({f'targets.models.{c}.flux_log_sigma': 1.2 for c in ('ELG', 'BGS', 'LRG', 'QSO', 'Star')})}),
    # requests
    'JR1': (A, {'REQ': json.dumps({'count': 40, 'targets_per_request': 16, 'minimum_completion_fraction': 1.0,
                                   'window_nights': 1, 'completion_reward': 1500.0})}),
    'JR2': (A, {'REQ': json.dumps({'count': 12, 'targets_per_request': 4, 'completion_reward': 5000.0,
                                   'include_required_targets': True})}),
    # budget
    'JB1': (A, {'WALL': '60'}),
}
# ---- historical extreme events (easter-egg candidates): real dates/sites, the engine's event types
def hist(start, lat, lon, nights=120, **env):
    return dict(WEIRD_START=start, WEIRD_LAT=str(lat), WEIRD_LON=str(lon), WEIRD_NIGHTS=str(nights), **env)
def tgt(tid, ra, dec, flux=1.5, w=5.0):
    return {'target_id': tid, 'ra_deg': ra, 'dec_deg': dec, 'target_class': 'QSO', 'feature_flux': flux,
            'science_weight': w, 'required': 'false'}
def rq(tids, issued, deadline, reward, reason):
    return {'target_ids': tids, 'issued_at_utc': issued, 'deadline_utc': deadline, 'completion_reward': reward,
            'reason': reason, 'minimum_completed': len(tids)}
W.update({
    # SN 1054 (天关客星, Song dynasty records, Kaifeng): guest star in Taurus from 1054-07-04
    'H1054': (A, hist('1054-06-01', 34.8, 114.3, TARGET_ADD=json.dumps([tgt('GUEST1054', 83.633, 22.0145)]),
                      REQ_ADD=json.dumps([rq(['GUEST1054'], '1054-07-04T12:00:00Z', '1054-07-30T12:00:00Z', 5000.0,
                                             'guest star near Tianguan (zeta Tauri)')]))),
    # Tycho's supernova 1572 (Hven) with a cold northern winter
    'H1572': (A, hist('1572-11-01', 55.9, 12.7, TARGET_ADD=json.dumps([tgt('SN1572', 6.33, 64.14)]),
                      REQ_ADD=json.dumps([rq(['SN1572'], '1572-11-11T18:00:00Z', '1572-11-20T18:00:00Z', 3000.0, 'new star in Cassiopeia')]),
                      EVENT_PATCH=json.dumps({'weather_events.conditions.cold_wave.count': 10}))),
    # Carrington event 1859-09-01 (Redhill): geomagnetic storm -> sky glow (cold-wave-like sky loss) + instrument failures
    'H1859': (A, hist('1859-08-15', 51.2, -0.17, EVENT_PATCH=json.dumps({
        'instrument_fault.count': 4, 'instrument_fault.instrument_efficiency_multiplier_range': [0.2, 0.5],
        'weather_events.conditions.cold_wave.count': 8, 'weather_events.conditions.cold_wave.sky_quality_multiplier': 0.4,
        'weather_events.conditions.cold_wave.transparency_multiplier': 0.8}))),
    # Krakatoa 1883-08-27: volcanic haze for months (smoggy, long, strong)
    'H1883': (A, hist('1883-09-01', -6.1, 106.8, EVENT_PATCH=json.dumps({
        'weather_events.conditions.smoggy.count': 12, 'weather_events.conditions.smoggy.duration_slots': [200, 600],
        'weather_events.conditions.smoggy.scope_weights': {'ALL': 1.0},
        'weather_events.conditions.smoggy.transparency_multiplier': 0.45, 'weather_events.conditions.smoggy.sky_quality_multiplier': 0.6}))),
    # Tunguska 1908-06-30: bright nights (sky glow) for weeks
    'H1908': (A, hist('1908-06-15', 45.0, 5.0, nights=90, EVENT_PATCH=json.dumps({
        'weather_events.conditions.cold_wave.count': 6, 'weather_events.conditions.cold_wave.duration_slots': [100, 300],
        'weather_events.conditions.cold_wave.sky_quality_multiplier': 0.35}))),
    # Tambora 1815 -> 1816 'year without a summer': cold waves all season
    'H1816': (A, hist('1816-05-01', 41.0, -72.0, EVENT_PATCH=json.dumps({
        'weather_events.conditions.cold_wave.count': 25, 'weather_events.conditions.cold_wave.transparency_multiplier': 0.6,
        'weather_events.conditions.cold_wave.seeing_multiplier': 1.4}))),
    # Valdivia 1960-05-22 M9.5 (Cerro Tololo region): megaquakes, slow recovery
    'H1960': (D, hist('1960-05-01', -30.2, -70.8, EVENT_PATCH=json.dumps({
        'earthquake.count': 4, 'earthquake.magnitude_range': [8.5, 9.5], 'earthquake.decay_nights': 9.0}))),
    # SN 1987A (Las Campanas) on 1987-02-24 + target-of-opportunity request
    'H1987': (B, hist('1987-02-01', -29.0, -70.7, TARGET_ADD=json.dumps([tgt('SN1987A', 83.8667, -69.2697, flux=3.0, w=8.0)]),
                      REQ_ADD=json.dumps([rq(['SN1987A'], '1987-02-24T23:00:00Z', '1987-02-27T09:00:00Z', 4000.0, 'supernova in the LMC')]))),
    # Pinatubo 1991-06-15: year-long stratospheric haze
    'H1991': (C, hist('1991-07-01', 19.8, -155.5, EVENT_PATCH=json.dumps({
        'weather_events.conditions.smoggy.count': 10, 'weather_events.conditions.smoggy.duration_slots': [300, 900],
        'weather_events.conditions.smoggy.scope_weights': {'ALL': 1.0}, 'weather_events.conditions.smoggy.transparency_multiplier': 0.7}))),
    # GW170817 / AT2017gfo in NGC 4993: one-night follow-up of a kilonova, plus rocket launches (modern sky)
    'H2017': (A, hist('2017-07-20', -30.2, -70.8, TARGET_ADD=json.dumps([tgt('AT2017gfo', 197.4504, -23.3815, flux=2.0, w=8.0)]),
                      REQ_ADD=json.dumps([rq(['AT2017gfo'], '2017-08-17T23:00:00Z', '2017-08-18T10:00:00Z', 3000.0, 'kilonova counterpart of GW170817')]),
                      EVENT_PATCH=json.dumps({'rocket_launch.count': 30}))),
})
# ---- combined extremes (interaction effects)
W.update({
    'XC1': (A, {'STRESS_ROWS': json.dumps([
        {'event_type': 'pointing_offset', 'trigger_mode': 'at_survey_start', 'alt_offset_rad': '0.02000000', 'az_offset_rad': '-0.01500000'},
        {'event_type': 'data_loss', 'trigger_mode': 'fixed_date', 'trigger_ref': '2026-12-01T03:00:00Z',
         'window_start_fraction': '0.200000', 'window_end_fraction': '0.700000', 'window_max_fraction': '1.000000'}]),
        'EVENT_PATCH': json.dumps({'instrument_fault.count': 5, 'instrument_fault.instrument_efficiency_multiplier_range': [0.3, 0.6],
                                   'terrain_obstruction.sector_count': [3, 5], 'terrain_obstruction.width_deg_range': [60.0, 120.0],
                                   'terrain_obstruction.max_altitude_deg_range': [50.0, 68.0],
                                   'quality.seeing_arcsec.night_sigma': 0.32, 'quality.transparency.night_sigma': 0.12,
                                   'quality.sky_quality.night_sigma': 0.2})}),
    'XC2': (A, ev({'weather_events.conditions.cold_wave.count': 12, 'weather_events.conditions.cold_wave.transparency_multiplier': 0.45,
                   'earthquake.count': 5, 'earthquake.magnitude_range': [7.0, 8.5], 'earthquake.decay_nights': 9.0,
                   'earthquake.sky_quality_impact_coefficient': 0.4,
                   'weather_events.conditions.cloudy.count': 25, 'weather_events.sector_width_deg_range': [120.0, 240.0],
                   'weather_events.sector_altitude_limit_deg_range': [70.0, 89.0],
                   'rocket_launch.count': 25, 'rocket_launch.max_altitude_deg': [60.0, 85.0],
                   'background_closure.start_probability_per_open_slot': 0.024})),
    'XC3': (A, dict(scp({'required.penalty_per_missing': 500, 'uniformity.weight': 20000.0, 'reporting.false_penalty': -1000,
                         'reporting.false_report_free_allowance': 0, 'reporting.max_consecutive_reports': 1,
                         'reporting.correct_reward': 1000}),
                    CAT_PATCH=json.dumps({'targets.required_fraction': 0.2}), EVENT_PATCH=json.dumps({'instrument_fault.count': 3}),
                    REQ=json.dumps({'count': 20, 'targets_per_request': 12, 'minimum_completion_fraction': 1.0,
                                    'window_nights': 1, 'completion_reward': 800.0}))),
    'XC4': (B, dict(WEIRD_LAT='-60', WEIRD_START='2027-05-01', WEIRD_NIGHTS='100',
                    CAT_PATCH=json.dumps({'observability.minimum_altitude_deg': 50.0, 'footprint.n_components': 2,
                                          'footprint.component_area_weights': [0.5, 0.5],
                                          'footprint.component_centers': [[60.0, -50.0], [250.0, -70.0]]}),
                    EVENT_PATCH=json.dumps({'survey.slot_seconds': 600, 'terrain_obstruction.max_altitude_deg_range': [55.0, 65.0]}),
                    STRESS_ROWS=json.dumps([{'event_type': 'pointing_offset', 'trigger_mode': 'at_survey_start',
                                             'alt_offset_rad': '0.01000000', 'az_offset_rad': '0.01200000'}]))),
    'XC5': (A, hist('1054-06-01', 34.8, 114.3, TARGET_ADD=json.dumps([tgt('GUEST1054', 83.633, 22.0145)]),
                    REQ_ADD=json.dumps([rq(['GUEST1054'], '1054-07-04T12:00:00Z', '1054-07-30T12:00:00Z', 5000.0, 'guest star')]),
                    EVENT_PATCH=json.dumps({'terrain_obstruction.max_altitude_deg_range': [55.0, 65.0],
                                            'weather_events.conditions.cold_wave.count': 10,
                                            'weather_events.conditions.cold_wave.transparency_multiplier': 0.5}),
                    STRESS_ROWS=json.dumps([{'event_type': 'pointing_offset', 'trigger_mode': 'at_survey_start',
                                             'alt_offset_rad': '-0.01700000', 'az_offset_rad': '0.01300000'}]))),
    'XC6': (D, hist('1960-05-01', -30.2, -70.8, EVENT_PATCH=json.dumps({
        'earthquake.count': 4, 'earthquake.magnitude_range': [8.5, 9.5], 'earthquake.decay_nights': 9.0,
        'instrument_fault.count': 6, 'weather_events.conditions.cold_wave.count': 12,
        'weather_events.conditions.cold_wave.transparency_multiplier': 0.45, 'quality.transparency.night_sigma': 0.12,
        'terrain_obstruction.max_altitude_deg_range': [55.0, 70.0], 'rocket_launch.count': 30}),
        SCORE_PATCH=json.dumps({'reporting.max_consecutive_reports': 1, 'reporting.false_penalty': -500}),
        REQ=json.dumps({'count': 15, 'targets_per_request': 10, 'minimum_completion_fraction': 1.0, 'window_nights': 2,
                        'completion_reward': 600.0}),
        STRESS_ROWS=json.dumps([{'event_type': 'pointing_offset', 'trigger_mode': 'at_survey_start',
                                 'alt_offset_rad': '0.03500000', 'az_offset_rad': '-0.02500000'},
                                {'event_type': 'data_loss', 'trigger_mode': 'fixed_date', 'trigger_ref': '1960-07-01T03:00:00Z',
                                 'window_start_fraction': '0.100000', 'window_end_fraction': '0.600000', 'window_max_fraction': '1.000000'}]))),
})

# ---- polar night / far-future epochs (round 3)
W.update({
    # Kunlun station, Dome A (China's Antarctic observatory): polar night, 24 h darkness for weeks around the June solstice
    'P1': (B, hist('2027-05-01', -80.42, 77.1, nights=100, CAT_PATCH=json.dumps({'footprint.n_components': 2, 'footprint.component_area_weights': [0.5, 0.5], 'footprint.component_centers': [[60.0, -45.0], [240.0, -45.0]]}))),
    # Amundsen-Scott South Pole (SPT/BICEP site): every star at constant altitude, azimuth degenerate at the pole
    'P2': (B, hist('2027-05-01', -89.99, -45.0, nights=100, CAT_PATCH=json.dumps({'footprint.n_components': 2, 'footprint.component_area_weights': [0.5, 0.5], 'footprint.component_centers': [[60.0, -45.0], [240.0, -45.0]]}))),
    # Dome A with a nautical-twilight limit: the Sun stays below -12 deg around the solstice (24 h darkness)
    'P4': (B, hist('2027-05-01', -80.42, 77.1, nights=100,
                   CAT_PATCH=json.dumps({'footprint.n_components': 2, 'footprint.component_area_weights': [0.5, 0.5],
                                         'footprint.component_centers': [[60.0, -45.0], [240.0, -45.0]],
                                         'observability.sun_altitude_limit_deg': -12.0}),
                   EVENT_PATCH=json.dumps({'survey.sun_altitude_limit_deg': -12.0}))),
    # PEARL, Eureka (80N): northern polar night
    'P3': (A, hist('2026-11-01', 80.05, -86.42, nights=100)),
    # Halley's comet return (2061-07-28), Lenghu (Qinghai)
    'F1': (A, hist('2061-06-01', 38.6, 93.9, nights=120)),
    # far future: year 3001
    'F2': (C, hist('3001-01-01', 32.3, 80.0, nights=120)),
    # last legal epoch region
    'F3': (A, hist('9998-01-01', 19.8, -155.5, nights=120)),
})

# ---- request-heavy A/B worlds for rq_urg_intra (round 3)
def rqs(count, tpr, frac, win, reward):
    return {'REQ': json.dumps({'count': count, 'targets_per_request': tpr, 'minimum_completion_fraction': frac,
                               'window_nights': win, 'completion_reward': reward})}
W.update({
    'RQ1': (('A', 8201, 0), rqs(20, 8, 1.0, 1, 800.0)),
    'RQ2': (('B', 8202, 0), rqs(15, 6, 0.8, 2, 600.0)),
    'RQ3': (('C', 8203, 0), rqs(25, 10, 1.0, 1, 1000.0)),
    'RQ4': (('D', 8204, 0), rqs(12, 5, 1.0, 3, 500.0)),
    'RQ5': (('A', 8205, 2), rqs(40, 16, 1.0, 1, 1500.0)),
    'RQ6': (('B', 8206, 0), rqs(30, 12, 0.9, 2, 1200.0)),
})

# ---- A1-D1-like cards (formal cards added 2026-10-06): ~50-70 requests, most of them unrewarded (min 1 of 3-5
# targets), a few worth 300-500; more weather events and faults. The engine re-checks every request against every
# ledger record at each step, so these cards press on the 1800 s real-time cap.
def v5(zero, big, ev, faults, **env):
    groups = [{'count': zero, 'ntargets': [3, 4, 5], 'min': 1, 'reward': 0.0}]
    groups += [{'count': c, 'ntargets': [3, 4, 5], 'min': m, 'reward': r} for c, m, r in big]
    ev = dict(ev, **{'instrument_fault.count': faults})
    return dict(REQ_V5=json.dumps({'groups': groups}), EVENT_PATCH=json.dumps(ev), **env)
W.update({
    'V5A': (('A', 8301, 0), v5(40, [(3, 2, 500.0), (1, 3, 350.0), (1, 2, 300.0)],
                              {'weather_events.conditions.cloudy.count': 14, 'weather_events.conditions.smoggy.count': 10}, 4)),
    'V5B': (('B', 8302, 0), v5(48, [(3, 2, 500.0), (2, 2, 300.0), (1, 2, 400.0)],
                              {'weather_events.conditions.cloudy.count': 16, 'weather_events.conditions.smoggy.count': 10,
                               'weather_events.conditions.rainy.count': 8}, 5)),
    'V5C': (('C', 8303, 0), v5(48, [(2, 2, 500.0), (2, 2, 350.0), (2, 2, 450.0)],
                              {'weather_events.conditions.cloudy.count': 14, 'weather_events.conditions.smoggy.count': 8,
                               'weather_events.conditions.rainy.count': 10}, 4)),
    'V5D': (('D', 8304, 0), v5(59, [(3, 2, 300.0), (2, 2, 400.0), (1, 2, 350.0)],
                              {'weather_events.conditions.cloudy.count': 24, 'weather_events.conditions.smoggy.count': 14,
                               'weather_events.conditions.rainy.count': 6}, 5)),
    'V5B2': (('B', 8312, 1), v5(80, [(3, 2, 500.0), (2, 2, 300.0), (1, 2, 400.0)],
                               {'weather_events.conditions.cloudy.count': 16, 'weather_events.conditions.smoggy.count': 10,
                                'weather_events.conditions.rainy.count': 8}, 5)),
})

W.update({
    # C1-like: long unannounced closures (mean ~20 slots) on top of the A1-D1 request load
    'V5C2': (('C', 8313, 0), v5(48, [(2, 2, 500.0), (2, 2, 350.0), (2, 2, 450.0)],
                               {'weather_events.conditions.cloudy.count': 14, 'weather_events.conditions.smoggy.count': 8,
                                'weather_events.conditions.rainy.count': 10,
                                'background_closure.start_probability_per_open_slot': 0.02,
                                'background_closure.reopen_probability_per_closed_slot': 0.05}, 4)),
})

if __name__ == '__main__':
    import sys
    for n in (sys.argv[1:] or W):
        (t, s, m), env = W[n]
        print(n, t, s, m, json.dumps(env))
