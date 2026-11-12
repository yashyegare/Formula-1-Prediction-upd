import {describe,it,expect} from 'vitest';
import {chooseRound,curveColor,intelSeasonSchema,observedGain,expectedGain,pointAtLap,raceLabel,topTenProbability,visibleReplayDrivers,type IntelDriver,type IntelSeason,type Replay} from './raceIntel';
export const sampleDriver:IntelDriver={driverId:'russell',driverCode:'RUS',surname:'Russell',constructorId:'mercedes',grid:1,p_podium:.6,p_points:.25,p_out:.15,expected_position:4,sim_dnf_rate:.1,actual_position:1,observed_swing:0,sim_swing_mean:3};
export const sampleSeason:IntelSeason={season:2026,n_sims:2000,next_round:2,mechanism:{swing_mean:1,swing_sd:3,dnf_rate:.1},races:[{year:2026,round:1,name:'Australian Grand Prix',date:'2026-03-08',status:'raced',n_drivers:1,drivers:[sampleDriver]},{year:2026,round:2,name:'Chinese Grand Prix',date:'2026-03-15',status:'scheduled',n_drivers:1,drivers:[sampleDriver]}],season_attribution:{accuracy:.7,n_misses:3,cause_share:{other:1},evidence:{scored:10}}};
describe('Race Intel interpretation',()=>{
  it('shows inclusive top-ten probability without confusing it with the P4–10 bucket or DNF',()=>{
    expect(topTenProbability(sampleDriver)).toBe(.85);expect(sampleDriver.sim_dnf_rate).not.toBe(sampleDriver.p_out);
  });
  it('defaults to the latest completed analysis when official results are ahead',()=>{
    expect(chooseRound(sampleSeason,{season:2026,results_through_round:10})).toBe(1);
    expect(chooseRound(sampleSeason,null)).toBe(1);
    expect(chooseRound(sampleSeason,{season:2026,results_through_round:1})).toBe(2);
  });
  it('honors a valid requested round and rejects unknown round links',()=>{
    expect(chooseRound(sampleSeason,{season:2026,results_through_round:10},2)).toBe(2);
    expect(chooseRound(sampleSeason,{season:2026,results_through_round:10},999)).toBe(1);
    expect(raceLabel(sampleSeason.races[1]!,10)).toBe('Archived projection');
  });
  it('uses a consistent gained-places sign and omits pit-lane changes',()=>{
    expect(expectedGain(sampleDriver)).toBe(-3);expect(observedGain(sampleDriver)).toBe(0);
    expect(expectedGain({...sampleDriver,grid:0})).toBeNull();expect(observedGain({...sampleDriver,grid:0})).toBeNull();
  });
  it('shows a selected driver even outside the six default traces and preserves colors',()=>{
    const drivers=Array.from({length:10},(_,i)=>({driverId:`driver${i}`,final_position:i+1,curve:[]}));
    const doc:Replay={round:1,n_laps:50,sample_laps:[],drivers};
    const color=curveColor('driver9');
    expect(visibleReplayDrivers(doc,drivers.map(d=>d.driverId),'driver9').some(d=>d.driverId==='driver9')).toBe(true);
    expect(curveColor('driver9')).toBe(color);expect(visibleReplayDrivers(doc,[],null)).toHaveLength(6);
  });
  it('does not inspect future samples when scrubbing between recorded laps',()=>{
    const curve:Replay['drivers'][number]['curve']=[[1,.1,.2,.7,12],[5,.8,.1,.1,3]];
    expect(pointAtLap(curve,4)?.[1]).toBe(.1);expect(pointAtLap(curve,0)).toBeNull();
  });
  it('rejects invalid probabilities and malformed race dates',()=>{
    expect(intelSeasonSchema.safeParse(sampleSeason).success).toBe(true);
    expect(intelSeasonSchema.safeParse({...sampleSeason,races:[{...sampleSeason.races[0],date:'invalid'}]}).success).toBe(false);
    expect(intelSeasonSchema.safeParse({...sampleSeason,races:[{...sampleSeason.races[0],drivers:[{...sampleDriver,p_podium:1.4}]}]}).success).toBe(false);
  });
});
