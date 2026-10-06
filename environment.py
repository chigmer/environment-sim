import random
import time
import sys
from collections import deque
from pathlib import Path
import pygame

TICKS_PER_DAY = 24
DAYS_PER_MONTH = 30
MATURITY_DAYS = 3 * DAYS_PER_MONTH
GESTATION_DAYS = 3 * DAYS_PER_MONTH
REPRODUCTION_COOLDOWN_DAYS = DAYS_PER_MONTH
MAX_AGE_DAYS = 12 * DAYS_PER_MONTH
MAX_DAILY_DEATH_CHANCE = 0.05
DAILY_FIGHT_CHANCE = 0.01
DAILY_CONCEPTION_CHANCE = 0.1
RAIN_CHANCE = 0.15
MAX_RAIN_DAYS = 2


class Entity:
    """Shared identity, position, and health for plants and animals."""

    def __init__(self, name: str, width: int, height: int, health: int = 100, age: int = 0):
        self.name = name
        self.row = width
        self.column = height
        self.x = random.randint(0, width - 1)
        self.y = random.randint(0, height - 1)
        self.icon = name[0].upper()
        self.health = health
        self.age = age

    def move(self):
        """Stationary by default; animals provide their own movement."""
        pass


class Animal(Entity):
    def __init__(
        self,
        name: str,
        range_: int,
        width: int,
        height: int,
        diet: str = "herbivore",
        size: str = "small",
        health: int = 100,
        hunger: int = 100,
        thirst: int = 100,
        age: int = 0,
        energy: int = 100,
        sex: str = "random",
    ):
        super().__init__(name, width, height, health, age)
        self.range_ = range_
        self.diet = diet
        self.size = size
        self.hunger = hunger
        self.thirst = thirst
        self.energy = energy
        self.sex = random.choice(("female", "male")) if sex == "random" else sex
        self.pregnancy_days = 0
        self.reproduction_cooldown = 0
        self.action = "idle"
        self.seed_cargo = []

    def advance_day(self, world: "World") -> bool:
        """Age one day, progress pregnancy, and apply age-related mortality."""
        self.age += 1
        self.reproduction_cooldown = max(0, self.reproduction_cooldown - 1)

        if self.pregnancy_days > 0:
            self.pregnancy_days -= 1
            if self.pregnancy_days == 0:
                world.entities.append(self.give_birth())

        age_fraction = min(self.age / MAX_AGE_DAYS, 1.0)
        death_chance = 0.0001 + (MAX_DAILY_DEATH_CHANCE - 0.0001) * age_fraction
        if world.life_rng.random() < death_chance:
            self.health = 0
            self.action = "died_of_old_age"
            return False

        return self.health > 0

    def can_reproduce_with(self, other: "Animal") -> bool:
        """Whether this female and a nearby same-species animal meet mating requirements."""
        nearby = max(abs(self.x - other.x), abs(self.y - other.y)) <= 1
        return (
            self is not other
            and self.name == other.name
            and self.sex == "female"
            and other.sex == "male"
            and nearby
            and self.age >= MATURITY_DAYS
            and other.age >= MATURITY_DAYS
            and self.pregnancy_days == 0
            and self.reproduction_cooldown == 0
            and other.reproduction_cooldown == 0
            and min(self.health, other.health) >= 50
            and min(self.hunger, other.hunger, self.thirst, other.thirst) >= 50
            and min(self.energy, other.energy) >= 30
        )

    def conceive(self, partner: "Animal"):
        """Start a gestation and put both parents on a short mating cooldown."""
        self.pregnancy_days = GESTATION_DAYS
        self.reproduction_cooldown = REPRODUCTION_COOLDOWN_DAYS
        partner.reproduction_cooldown = REPRODUCTION_COOLDOWN_DAYS
        self.action = "pregnant"
        partner.action = "mate"

    def give_birth(self) -> "Animal":
        """Create one newborn of the mother's species at her current location."""
        baby = Animal(
            name=self.name,
            range_=self.range_,
            width=self.row,
            height=self.column,
            diet=self.diet,
            size=self.size,
            health=100,
            hunger=100,
            thirst=100,
            age=0,
            energy=100,
        )
        baby.x, baby.y = self.x, self.y
        self.action = "give_birth"
        return baby

    def fight(self, opponent: "Animal") -> bool:
        """Inflict significant damage on both animals in a same-species fight."""
        nearby = max(abs(self.x - opponent.x), abs(self.y - opponent.y)) <= 1
        if self is opponent or self.name != opponent.name or not nearby:
            return False

        self.health = max(0, self.health - random.randint(20, 40))
        opponent.health = max(0, opponent.health - random.randint(20, 40))
        self.action = "fight"
        opponent.action = "fight"
        return True

    def move(self,world: "World"):
        dx = random.randint(-self.range_, self.range_)
        dy = random.randint(-self.range_, self.range_)
        new_x = (self.x + dx) % self.row
        new_y = (self.y + dy) % self.column

        if world.is_walkable(new_x, new_y):
            self.x = new_x
            self.y = new_y
        self.action = "move"
        
    def update_needs(self):
        """Update the animal's hunger and thirst levels over time. call this method per tick"""
        self.hunger = max(0, self.hunger - 1)  # Decrease hunger
        self.thirst = max(0, self.thirst - 1)  # Decrease thirst
        self.energy = min(100, self.energy + 1)  # Recover a little energy each tick.
        # max() prevents the values from going below 0, which could represent starvation or dehydration.
        
        if self.hunger == 0 or self.thirst == 0:
            self.health = max(0, self.health - random.randint(1, 5))  # Decrease health if starving or dehydrated

    def digest_seeds(self, world: "World"):
        """Digest eaten fruit and deposit its seeds at the animal's location."""
        remaining_seeds = []
        for plant, seed_count, ticks_left in self.seed_cargo:
            ticks_left -= 1
            if ticks_left <= 0:
                if plant.plant_seed(world, self.x, self.y, seed_count):
                    self.action = "poop_seeds"
                else:
                    remaining_seeds.append((plant, seed_count, 0))
            else:
                remaining_seeds.append((plant, seed_count, ticks_left))
        self.seed_cargo = remaining_seeds

    def seek_water(self, world: "World", thirst_restore: int = 100) -> bool:
        """Move toward reachable water and drink when next to it.

        Returns True only on a tick when the animal drinks. Call once per
        simulation tick while the animal needs water.

        not my code
        """
        water_cells = {
            (x, y)
            for y in range(world.max_column)
            for x in range(world.max_row)
            if world.get_terrain(x, y) == "water"
        }
        if not water_cells:
            self.move(world)
            return False

        # Any walkable cell directly beside water is a valid drinking spot.
        goals = set()
        for water_x, water_y in water_cells:
            for x, y in (
                (water_x - 1, water_y),
                (water_x + 1, water_y),
                (water_x, water_y - 1),
                (water_x, water_y + 1),
            ):
                if (
                    0 <= x < world.max_row
                    and 0 <= y < world.max_column
                    and world.is_walkable(x, y)
                ):
                    goals.add((x, y))

        # Breadth-first search finds a shortest route without crossing blocked terrain.
        start = (self.x, self.y)
        queue = deque([start])
        previous = {start: None}
        destination = None

        while queue:
            current = queue.popleft()
            if current in goals:
                destination = current
                break

            x, y = current
            for neighbor in (
                (x - 1, y),
                (x + 1, y),
                (x, y - 1),
                (x, y + 1),
            ):
                if (
                    0 <= neighbor[0] < world.max_row
                    and 0 <= neighbor[1] < world.max_column
                    and neighbor not in previous
                    and world.is_walkable(*neighbor)
                ):
                    previous[neighbor] = current
                    queue.append(neighbor)

        if destination is None:
            # Wander instead of standing still if every water source is blocked.
            self.move(world)
            return False

        path = []
        current = destination
        while current is not None:
            path.append(current)
            current = previous[current]
        path.reverse()

        if len(path) == 1:
            self.thirst = min(100, self.thirst + thirst_restore)
            self.action = "drink"
            return True

        steps = min(self.range_, len(path) - 1)
        if steps > 0:
            self.x, self.y = path[steps]

        if (self.x, self.y) == destination:
            self.thirst = min(100, self.thirst + thirst_restore)
            self.action = "drink"
            return True

        self.action = "move_to_water"
        return False

    def choose_action(self):
        """Determine the animal's next action based on its needs."""
        if self.hunger < 30:
            self.action = "searching for food"
        elif self.thirst < 30:
            self.action = "searching for water"
        else:
            self.action = "idle"
    def eat(self, world: "World", food=None) -> bool:
        """Eat only when food is available in this animal's exact cell."""
        if self.diet == "herbivore":
            fruit_plant = next(
                (
                    entity
                    for entity in world.entities
                    if isinstance(entity, Plant)
                    and entity.x == self.x
                    and entity.y == self.y
                    and entity.fruit_count > 0
                ),
                None,
            )
            if fruit_plant is not None:
                seeds = fruit_plant.harvest_fruit()
                if seeds:
                    self.seed_cargo.append((fruit_plant, seeds, 3))
            elif world.get_terrain(self.x, self.y) == "grass":
                world.terrain[self.y][self.x] = "bare_soil"
            else:
                return False

        elif self.diet == "carnivore":
            prey = food if isinstance(food, Animal) else next(
                (
                    entity
                    for entity in world.entities
                    if isinstance(entity, Animal)
                    and entity.diet == "herbivore"
                    and entity.x == self.x
                    and entity.y == self.y
                ),
                None,
            )
            if (
                prey is None
                or prey not in world.entities
                or prey.diet != "herbivore"
                or (prey.x, prey.y) != (self.x, self.y)
            ):
                return False
            world.entities.remove(prey)
        else:
            return False

        self.hunger = min(100, self.hunger + 40)
        self.action = "eat"
        return True

    def forage(self, world: "World") -> bool:
        """Seek fruit first, then grass; eat only after reaching its cell."""
        fruit_cells = {
            (entity.x, entity.y)
            for entity in world.entities
            if isinstance(entity, Plant) and entity.fruit_count > 0
        }
        grass_cells = {
            (x, y)
            for y in range(world.max_column)
            for x in range(world.max_row)
            if world.get_terrain(x, y) == "grass"
        }

        path = world.find_path((self.x, self.y), fruit_cells) if fruit_cells else []
        if not path:
            path = world.find_path((self.x, self.y), grass_cells)
        if not path:
            self.action = "search_for_food"
            return False

        steps = min(max(0, self.range_), len(path) - 1)
        if steps:
            self.x, self.y = path[steps]
        if (self.x, self.y) == path[-1] and self.eat(world):
            return True

        self.action = "forage"
        return False

    def hunt(self, world: "World", energy_per_step: int = 2) -> bool:
        """Chase the nearest reachable herbivore and eat it on contact.

        Chasing allows twice the normal movement range and spends energy per
        path step. Returns True if prey was eaten this tick.
        """
        prey_animals = [
            entity
            for entity in world.entities
            if isinstance(entity, Animal)
            and entity is not self
            and entity.diet == "herbivore"
        ]
        if not prey_animals:
            self.action = "search_for_food"
            return False
        energy_per_step = max(1, energy_per_step)

        prey_cells = {(prey.x, prey.y) for prey in prey_animals}
        path = world.find_path((self.x, self.y), prey_cells)
        if not path:
            self.action = "search_for_food"
            return False

        if len(path) == 1:
            return self.eat(world, next(
                prey for prey in prey_animals
                if (prey.x, prey.y) == (self.x, self.y)
            ))

        chase_range = max(1, self.range_ * 2)
        affordable_steps = self.energy // energy_per_step
        steps = min(chase_range, len(path) - 1, affordable_steps)
        if steps == 0:
            self.energy = min(100, self.energy + 5)
            self.action = "rest"
            return False

        self.x, self.y = path[steps]
        self.energy -= steps * energy_per_step

        prey = next(
            (
                target for target in prey_animals
                if (target.x, target.y) == (self.x, self.y)
            ),
            None,
        )
        if prey is not None:
            return self.eat(world, prey)

        self.action = "chase"
        return False

    def find_food(self, world: "World") -> bool:
        """Use the feeding behavior appropriate for this animal's diet."""
        if self.diet == "herbivore":
            return self.forage(world)
        if self.diet == "carnivore":
            return self.hunt(world)
        self.action = "idle"
        return False


class Plant(Entity):
    def __init__(
        self,
        name: str,
        width: int,
        height: int,
        plant_type: str = "tree",
        fruit_bearing: bool = False,
        health: int = 100,
        age: int = 0,
        water: int = 100,
        nutrients: int = 100,
        energy: int = 0,
        fruit_count: int = 3,
        growth: int = 0,
        seeds_per_fruit: int = 2,
    ):
        super().__init__(name, width, height, health, age)
        self.plant_type = plant_type
        self.fruit_bearing = fruit_bearing
        self.fruit_count = fruit_count if fruit_bearing else 0
        self.seeds_per_fruit = seeds_per_fruit
        self.water = water
        self.nutrients = nutrients
        self.energy = energy
        self.growth = growth
        #if growth reaches 10, the plant is mature and can produce fruit if fruit_bearing is True, else produce seeds for reproduction.
        self.action = "idle"

    def harvest_fruit(self):
        """Remove one ripe fruit and return its viable seed count."""
        if not self.fruit_bearing or self.fruit_count <= 0:
            return 0
        self.fruit_count -= 1
        return self.seeds_per_fruit

    def plant_seed(self, world: "World", x: int, y: int, seed_count: int = 1) -> bool:
        """Create seedlings from carried seeds on nearby empty, walkable cells."""
        if seed_count <= 0 or not (0 <= x < world.max_row and 0 <= y < world.max_column):
            return False

        candidates = [
            (x + dx, y + dy)
            for dx, dy in (
                (0, 0), (-1, 0), (1, 0), (0, -1), (0, 1),
                (-1, -1), (1, -1), (-1, 1), (1, 1),
            )
        ]
        random.shuffle(candidates)
        planted = 0
        for seed_x, seed_y in candidates:
            if not (0 <= seed_x < world.max_row and 0 <= seed_y < world.max_column):
                continue
            if not world.is_walkable(seed_x, seed_y):
                continue
            if any(
                isinstance(entity, Plant) and (entity.x, entity.y) == (seed_x, seed_y)
                for entity in world.entities
            ):
                continue

            seedling = Plant(
                name=self.name.split("_")[0] + "_seedling",
                width=world.max_row,
                height=world.max_column,
                plant_type=self.plant_type,
                fruit_bearing=self.fruit_bearing,
                health=50,
                water=50,
                nutrients=50,
                energy=0,
                fruit_count=0,
                growth=-1,
                seeds_per_fruit=self.seeds_per_fruit,
            )
            seedling.x, seedling.y = seed_x, seed_y
            world.entities.append(seedling)
            planted += 1
            if planted >= seed_count:
                break

        return planted > 0

    def update(self,world):
        if self.health > 0:
            self.water = max(0, self.water - 0.15)  # Decrease water level over time
            self.nutrients = max(0, self.nutrients - 0.1)  # Decrease nutrients level over time
            self.energy = min(100, self.energy + 0.5)  # Increase energy level over time
            self.photosynthesize()
            self.absorb_from_soil(world)
            self.grow()
            self.spread(world)



    
    def spread(self,world):
        if self.growth >= 10 and self.fruit_bearing and self.energy > 20 and self.water > 10 and self.nutrients > 10:
            self.fruit_count = min(5, self.fruit_count + 1)  # Produce fruit if mature
            self.energy = max(0, self.energy - 5)  # Energy cost for fruit production
            self.water = max(0, self.water - 2)  # Water cost for fruit production
            self.nutrients = max(0, self.nutrients - 1)
        elif self.growth >= 10 and not self.fruit_bearing and self.energy > 20 and self.water > 10 and self.nutrients > 10:
            self.energy = max(0, self.energy - 5)  # Energy cost for seed production
            self.water = max(0, self.water - 2)  # Water cost for seed production
            self.nutrients = max(0, self.nutrients - 1)
            x = self.x
            y = self.y
            range = random.choice(list(range(2, 5)))  # Randomly choose a range of 1 or 2 for seed dispersal
            neighboring_cells = [(x - (range), y), (x + (range), y), (x, y - (range)), (x, y + (range)), (x - (range), y - (range)), (x + (range), y + (range)), (x - (range), y + (range)), (x + (range), y - (range))]
            # 8 neighboring cells in a square pattern around the plant, spread seeds to a random walkable neighboring cell if possible
            for new_x, new_y in neighboring_cells:
                if 0 <= new_x < world.max_row and 0 <= new_y < world.max_column and world.is_walkable(new_x, new_y):
                    new_plant = Plant(
                                name=self.name + f"_{random.randint(1, 1000)}",  # Unique name for the new plant
                                width=world.max_row,
                                height=world.max_column,
                                plant_type=self.plant_type,
                                fruit_bearing=self.fruit_bearing,
                                growth=-1 #mimics a seedling that needs to grow before it can produce fruit or seeds
                            )
                    new_plant.x = new_x
                    new_plant.y = new_y
                    world.entities.append(new_plant)
                    break  # Spread only one seed per update cycle

            

    def photosynthesize(self, sunlight: float = 1.0):
        """Convert sunlight into energy, consuming water and nutrients."""
        if self.water > 0 and self.nutrients > 0:
            energy_gain = sunlight * 0.75  # Adjust the factor as needed
            self.energy = min(100, self.energy + energy_gain)
            self.water = max(0, self.water - 0.15)  # Water consumption during photosynthesis
            self.nutrients = max(0, self.nutrients - 0.1)  # Nutrient consumption during photosynthesis
    def absorb_from_soil(
        self,
        world: "World",
        water_absorption: float = 0.4,
        nutrient_absorption: float = 0.3,
    ):
        """Take available moisture from this plant's soil cell."""
        soil_water = world.soil_moisture[self.y][self.x]
        absorbed = min(water_absorption, soil_water, 100 - self.water)
        self.water += absorbed
        world.soil_moisture[self.y][self.x] -= absorbed
        self.nutrients = min(100, self.nutrients + nutrient_absorption)
    def grow(self):
        """Increase growth based on energy, water, and nutrients."""
        if self.energy > 20 and self.water > 10 and self.nutrients > 10:
            growth = 2  # Adjust the growth increment as needed
            self.growth = min(20, self.growth + growth)
            self.energy = max(0, self.energy - 5)  # Energy cost for growth
            self.water = max(0, self.water - 2)  # Water cost for growth
            self.nutrients = max(0, self.nutrients - 1)  # Nutrient cost for growth
            

class World:
    def __init__(self, max_row, max_column, entities=None, empty_cell="-", seed=None):
        self.entities = entities if entities is not None else []
        self.max_row = max_row  # grid width
        self.max_column = max_column  # grid height
        self.empty_cell = empty_cell.center(len(empty_cell) + 2)
        self.terrain = self.generate_terrain(seed)
        self.soil_moisture = [
            [50.0 for _ in range(self.max_row)]
            for _ in range(self.max_column)
        ]
        self.tick_count = 0
        self.day = 0
        self.weather = "clear"
        self.rain_days_remaining = 0
        self.weather_rng = random.Random(seed)
        self.life_rng = random.Random(None if seed is None else seed + 1)

        # Move entities off impassable cells if they spawned there.
        walkable = self.walkable_cells()
        for entity in self.entities:
            if not self.is_walkable(entity.x, entity.y) and walkable:
                entity.x, entity.y = random.choice(walkable)

    def generate_terrain(self, seed=None):
        rng = random.Random(seed)
        terrain = [
            ["grass" for _ in range(self.max_row)]
            for _ in range(self.max_column)
        ]

        # Random walks create clustered patches rather than scattered tiles.
        for terrain_type, patch_count, patch_size in [
            ("water", 5, 28),
            ("rock", 6, 14),
        ]:
            for _ in range(patch_count):
                x = rng.randrange(self.max_row)
                y = rng.randrange(self.max_column)

                for _ in range(patch_size):
                    terrain[y][x] = terrain_type
                    x = max(0, min(self.max_row - 1, x + rng.choice([-1, 0, 1])))
                    y = max(0, min(self.max_column - 1, y + rng.choice([-1, 0, 1])))

        return terrain

    def _start_new_day(self):
        """Set today's weather; a rain event lasts one or two full days."""
        self.day += 1

        if self.rain_days_remaining > 0:
            # Continue an existing event for its remaining day(s).
            self.rain_days_remaining -= 1
            self.weather = "rain"
        elif self.weather == "rain":
            # First clear day after rain: skip the rain chance for this day.
            self.weather = "clear"
        elif self.weather_rng.random() < RAIN_CHANCE:
            self.weather = "rain"
            duration = self.weather_rng.randint(1, MAX_RAIN_DAYS)
            self.rain_days_remaining = duration - 1
        else:
            self.weather = "clear"

    def _advance_weather(self):
        """Advance the calendar and roll weather at the beginning of each day."""
        new_day = self.tick_count % TICKS_PER_DAY == 0
        if new_day:
            self._start_new_day()
        self.tick_count += 1
        return new_day

    def _advance_animal_lives(self):
        """Age animals, complete pregnancies, and remove animals that die."""
        for animal in [entity for entity in self.entities if isinstance(entity, Animal)]:
            animal.advance_day(self)
        self.entities = [
            entity for entity in self.entities
            if not isinstance(entity, Animal) or entity.health > 0
        ]

    def _try_reproduction(self):
        """Allow at most one conception per eligible female per day."""
        females = [
            entity for entity in self.entities
            if isinstance(entity, Animal) and entity.sex == "female"
        ]
        males = [
            entity for entity in self.entities
            if isinstance(entity, Animal) and entity.sex == "male"
        ]

        for female in females:
            for male in males:
                if (
                    female.can_reproduce_with(male)
                    and self.life_rng.random() < DAILY_CONCEPTION_CHANCE
                ):
                    female.conceive(male)
                    break

    def _try_fights(self):
        """Give nearby same-species pairs a small daily chance to fight."""
        animals = [entity for entity in self.entities if isinstance(entity, Animal)]
        for index, animal in enumerate(animals):
            for opponent in animals[index + 1:]:
                nearby = max(abs(animal.x - opponent.x), abs(animal.y - opponent.y)) <= 1
                if (
                    animal.name == opponent.name
                    and nearby
                    and animal.age >= MATURITY_DAYS
                    and opponent.age >= MATURITY_DAYS
                    and animal.health > 0
                    and opponent.health > 0
                    and animal.action not in {"pregnant", "mate"}
                    and opponent.action not in {"pregnant", "mate"}
                    and self.life_rng.random() < DAILY_FIGHT_CHANCE
                ):
                    animal.fight(opponent)

        self.entities = [
            entity for entity in self.entities
            if not isinstance(entity, Animal) or entity.health > 0
        ]

    def is_walkable(self, x, y):
        return self.terrain[y][x] not in {"water", "rock"}
    def get_terrain(self, x, y):
        return self.terrain[y][x]
    def walkable_cells(self):
        return [
            (x, y)
            for y in range(self.max_column)
            for x in range(self.max_row)
            if self.is_walkable(x, y)
        ]

    def find_path(self, start, goals):
        """Return a shortest walkable path from start to any goal, including both endpoints."""
        goals = set(goals)
        if not goals:
            return []

        queue = deque([start])
        previous = {start: None}
        destination = None

        while queue:
            current = queue.popleft()
            if current in goals:
                destination = current
                break

            x, y = current
            for neighbor in (
                (x - 1, y),
                (x + 1, y),
                (x, y - 1),
                (x, y + 1),
            ):
                if (
                    0 <= neighbor[0] < self.max_row
                    and 0 <= neighbor[1] < self.max_column
                    and neighbor not in previous
                    and self.is_walkable(*neighbor)
                ):
                    previous[neighbor] = current
                    queue.append(neighbor)

        if destination is None:
            return []

        path = []
        current = destination
        while current is not None:
            path.append(current)
            current = previous[current]
        return list(reversed(path))

    def print_entities(self):
        unique_entities = set()
        print("\n" * 20)
        for entity in self.entities:
            movement_range = getattr(entity, "range_", 0)
            unique_entities.add((entity.icon, entity.name, movement_range))

        for icon, name, movement_range in sorted(unique_entities):
            print(f"{icon}: {name}\nMovement range: {movement_range}")

    def move_entities(self):
        new_day = self._advance_weather()

        for plant in [entity for entity in self.entities if isinstance(entity, Plant)]:
            plant.update(self)

        # Rain refills every plant's water reserve to its maximum.
        if self.weather == "rain":
            for y in range(self.max_column):
                for x in range(self.max_row):
                    self.soil_moisture[y][x] = 100.0
            for plant in self.entities:
                if isinstance(plant, Plant):
                    plant.water = 100

        animals = [entity for entity in self.entities if isinstance(entity, Animal)]
        for animal in animals:
            animal.update_needs()

        if new_day:
            self._advance_animal_lives()

        self.entities = [
            entity for entity in self.entities
            if not isinstance(entity, Animal) or entity.health > 0
        ]
        animals = [animal for animal in animals if animal.health > 0]

        # Let herbivores act first so predators chase their updated positions.
        animals.sort(key=lambda animal: animal.diet == "carnivore")
        for animal in animals:
            if animal.thirst < 30:
                animal.seek_water(self)
            elif animal.hunger < 30:
                animal.find_food(self)
            else:
                animal.move(self)

        for animal in animals:
            animal.digest_seeds(self)

        if new_day:
            self._try_reproduction()
            self._try_fights()
entities = []
width = 30
length = 18

entity_names = ["Tree", "Sunflower", "Sheep", "Rabbit", "Mouse", "Wolf", "Bush", "Cat", "Dog","Cow", "Deer", "Bear", "Fox", "Eagle", "Hawk"] + ["Tree","Tree","Fruit-Bearing Tree"] * 5 
entity_names += ["Wolf","Rabbit","Mouse","Sheep"] * 2
for name in entity_names:
    if name in {"Tree", "Bush", "Sunflower", "Fruit-Bearing Tree"}:
        entities.append(
            Plant(
                name,
                width,
                length,
                plant_type=name.lower(),
                fruit_bearing= True if name == "Fruit-Bearing Tree" else False,
            )
        )
    else:
        diet = "carnivore" if name in {"Cat", "Dog", "Wolf"} else "herbivore"
        entities.append(
            Animal(
                name,
                random.randint(1, 3),
                width,
                length,
                diet=diet,
                size="small",
            )
        )



# 20x32 tiles, each tile is 32x32 pixels, so the window size is 640x1024 pixels. The TILE_SIZE constant defines the size of each tile in pixels, and the TERRAIN_COLORS dictionary maps terrain types to their corresponding RGB color values for rendering.
# tile size subject to change
TILE_SIZE = 32  # Size of each tile in pixels
TERRAIN_COLORS = {
    "grass": (16,74,13),
    "water": (12, 177, 237),
    "rock": (30, 31, 30),
    "bare_soil": (92, 55, 7),
}

SPRITE_FILES = {
    "Rabbit": ("rabbit.png",),
    "Sheep": ("sheep.png",),
    "Mouse": ("mouse.png", "mouse_white.png"),
    "Wolf": ("wolf.png",),
    "Dog": ("wolf.png",),
    "Cat": ("cat.png",),
    "Cow": ("cow.png", "cow_brown.png"),
    "Deer": ("deer.png",),
    "Bear": ("bear.png",),
    "Eagle": ("bird.png",),
    "Hawk": ("bird.png",),
    "Tree": ("tree.png",),
    "Fruit-Bearing Tree": ("tree.png",),
    "Bush": ("tree.png",),
    "Sunflower": ("flower.png",),
}

MIN_SIMULATION_TICK_MS = 100
MAX_SIMULATION_TICK_MS = 3000
SIMULATION_SPEED_STEP_MS = 100


def adjust_simulation_speed(tick_ms, key):
    """Left arrow speeds up; right arrow slows down the simulation."""
    if key == pygame.K_LEFT:
        return max(MIN_SIMULATION_TICK_MS, tick_ms - SIMULATION_SPEED_STEP_MS)
    if key == pygame.K_RIGHT:
        return min(MAX_SIMULATION_TICK_MS, tick_ms + SIMULATION_SPEED_STEP_MS)
    return tick_ms


def load_entity_sprites():
    """Load and cache the cleaned PNG sprites, preserving pixel-art edges."""
    bundle_root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    sprite_dir = bundle_root / "assets" / "sprites"
    loaded = {}
    for species, filenames in SPRITE_FILES.items():
        loaded[species] = []
        for filename in filenames:
            path = sprite_dir / filename
            if path.exists():
                loaded[species].append(pygame.image.load(str(path)).convert_alpha())
    return loaded



def main_simulation(entities):
    field = World(width, length, entities=entities)
    pygame.init()
    sidebar_width = 300
    map_width_px = width * TILE_SIZE
    screen = pygame.display.set_mode((map_width_px + sidebar_width, length * TILE_SIZE))
    pygame.display.set_caption("Ecosystem Simulation")
    clock = pygame.time.Clock()
    coordinate_font = pygame.font.SysFont("arial", 14, bold=True)
    sidebar_title_font = pygame.font.SysFont("arial", 22, bold=True)
    event_font = pygame.font.SysFont("arial", 15)
    muted_font = pygame.font.SysFont("arial", 12)
    entity_sprites = load_entity_sprites()
    sprite_choices = {}
    events = []
    simulation_tick_ms = 1000
    simulation_time = 0
    paused = False
    running = True
    while running:
        elapsed_ms = clock.tick(60)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            elif event.type == pygame.KEYDOWN and event.key == pygame.K_SPACE:
                paused = not paused
            elif event.type == pygame.KEYDOWN and event.key in (pygame.K_LEFT, pygame.K_RIGHT):
                simulation_tick_ms = adjust_simulation_speed(simulation_tick_ms, event.key)

        if not paused:
            simulation_time += elapsed_ms

        # Clear the screen
        screen.fill((0, 0, 0))

        # Draw the terrain
        for y in range(field.max_column):
            for x in range(field.max_row):
                terrain_type = field.get_terrain(x, y)
                color = TERRAIN_COLORS.get(terrain_type, (255, 255, 255))
                pygame.draw.rect(screen, color, (x * TILE_SIZE, y * TILE_SIZE, TILE_SIZE, TILE_SIZE))

        # Draw clear, subtle borders around each tile.
        grid_color = (8, 24, 20)
        for x in range(field.max_row + 1):
            pixel_x = x * TILE_SIZE
            pygame.draw.line(screen, grid_color, (pixel_x, 0), (pixel_x, field.max_column * TILE_SIZE), 1)
        for y in range(field.max_column + 1):
            pixel_y = y * TILE_SIZE
            pygame.draw.line(screen, grid_color, (0, pixel_y), (map_width_px, pixel_y), 1)

        # Draw transparent pixel-art entity textures centered in their grid cells.
        for entity in sorted(field.entities, key=lambda item: (isinstance(item, Animal), item.y)):
            species = entity.name.split("_")[0]
            options = entity_sprites.get(species, [])
            if options:
                if id(entity) not in sprite_choices:
                    sprite_choices[id(entity)] = random.choice(options)
                sprite = sprite_choices[id(entity)]
                sprite_width_limit = round(TILE_SIZE * 1.45)
                sprite_height_limit = round(TILE_SIZE * (1.65 if isinstance(entity, Plant) else 1.35))
                scale = min(
                    sprite_width_limit / sprite.get_width(),
                    sprite_height_limit / sprite.get_height(),
                )
                sprite_size = (
                    max(1, round(sprite.get_width() * scale)),
                    max(1, round(sprite.get_height() * scale)),
                )
                scaled_sprite = pygame.transform.scale(sprite, sprite_size)
                sprite_rect = scaled_sprite.get_rect(
                    midbottom=(
                        entity.x * TILE_SIZE + TILE_SIZE // 2,
                        (entity.y + 1) * TILE_SIZE,
                    )
                )
                screen.blit(scaled_sprite, sprite_rect)
            else:
                fallback_color = (235, 92, 75) if isinstance(entity, Animal) else (95, 210, 115)
                pygame.draw.circle(
                    screen,
                    fallback_color,
                    (entity.x * TILE_SIZE + TILE_SIZE // 2, entity.y * TILE_SIZE + TILE_SIZE // 2),
                    max(3, TILE_SIZE // 3),
                )

        mouse_x, mouse_y = pygame.mouse.get_pos()
        hovered_cell = None
        if 0 <= mouse_x < field.max_row * TILE_SIZE and 0 <= mouse_y < field.max_column * TILE_SIZE:
            cell_x = mouse_x // TILE_SIZE
            cell_y = mouse_y // TILE_SIZE
            hovered_cell = (cell_x, cell_y)
            coordinate_label = f"PX ({mouse_x}, {mouse_y})   CELL ({cell_x}, {cell_y})"
        else:
            coordinate_label = f"PX ({mouse_x}, {mouse_y})   OUTSIDE MAP"

        coordinate_surface = coordinate_font.render(
            coordinate_label, True, (245, 245, 230)
        )
        coordinate_background = pygame.Rect(8, 8, coordinate_surface.get_width() + 18, 30)
        
        pygame.draw.rect(screen, (15, 24, 22), coordinate_background, border_radius=3)
        pygame.draw.rect(screen, (90, 120, 102), coordinate_background, width=1, border_radius=3)
        screen.blit(coordinate_surface, (17, 15))

        # Right-hand event tab/panel.
        panel_x = map_width_px
        panel_rect = pygame.Rect(panel_x, 0, sidebar_width, length * TILE_SIZE)
        pygame.draw.rect(screen, (20, 29, 28), panel_rect)
        pygame.draw.line(screen, (62, 84, 75), (panel_x, 0), (panel_x, panel_rect.height), 2)
        pygame.draw.rect(screen, (30, 45, 40), (panel_x + 14, 14, sidebar_width - 28, 60), border_radius=2)
        screen.blit(sidebar_title_font.render("EVENT LOG", True, (230, 238, 219)), (panel_x + 28, 24))
        screen.blit(muted_font.render(f"DAY {field.day:03d}   ·   {field.weather.upper()}", True, (156, 181, 159)), (panel_x + 29, 49))
        ticks_per_second = 1000 / simulation_tick_ms
        speed_label = f"SPEED {ticks_per_second:.1f} ticks/s   ·   ← / →"
        screen.blit(muted_font.render(speed_label, True, (156, 181, 159)), (panel_x + 29, 66))

        # Keep the latest events; each entry is timestamped by simulation day.
        event_top = 91
        inspector_height = 142
        inspector_y = panel_rect.bottom - inspector_height - 12
        visible_event_count = max(0, (inspector_y - event_top - 8) // 58)
        if not events:
            screen.blit(event_font.render("The forest is quiet.", True, (165, 180, 166)), (panel_x + 20, event_top + 10))
            screen.blit(muted_font.render("Events will appear as", True, (126, 145, 132)), (panel_x + 20, event_top + 35))
            screen.blit(muted_font.render("the simulation unfolds.", True, (126, 145, 132)), (panel_x + 20, event_top + 51))
        else:
            shown_events = events[-visible_event_count:] if visible_event_count else []
            for index, (day_label, message, color) in enumerate(reversed(shown_events)):
                y = event_top + index * 58
                pygame.draw.circle(screen, color, (panel_x + 23, y + 14), 4)
                screen.blit(muted_font.render(day_label, True, (137, 158, 143)), (panel_x + 36, y + 5))
                text = event_font.render(message[:30], True, color)
                screen.blit(text, (panel_x + 36, y + 24))
                pygame.draw.line(screen, (42, 58, 51), (panel_x + 18, y + 52), (panel_x + sidebar_width - 18, y + 52), 1)

        # Bottom-right inspector: entity details take precedence over terrain.
        inspector_rect = pygame.Rect(panel_x + 14, inspector_y, sidebar_width - 28, inspector_height)
        pygame.draw.rect(screen, (30, 45, 40), inspector_rect, border_radius=3)
        pygame.draw.rect(screen, (62, 84, 75), inspector_rect, width=1, border_radius=3)
        screen.blit(sidebar_title_font.render("CELL INFO", True, (230, 238, 219)), (inspector_rect.x + 14, inspector_rect.y + 10))

        if hovered_cell is None:
            info_heading = "Move cursor over the map"
            info_lines = ["Hover on a tile to inspect it."]
            info_color = (156, 181, 159)
        else:
            cell_x, cell_y = hovered_cell
            cell_entities = [
                entity for entity in field.entities
                if (entity.x, entity.y) == hovered_cell
            ]
            inspected = next(
                (entity for entity in cell_entities if isinstance(entity, Animal)),
                cell_entities[0] if cell_entities else None,
            )

            if inspected is not None and isinstance(inspected, Animal):
                info_heading = f"{inspected.name}  ·  {inspected.sex}"
                info_lines = [
                    f"Health {inspected.health}   Age {inspected.age} days",
                    f"Hunger {inspected.hunger}   Thirst {inspected.thirst}",
                    f"Action: {inspected.action.replace('_', ' ').title()}",
                ]
                if inspected.pregnancy_days > 0:
                    info_lines.append(f"Pregnant · {inspected.pregnancy_days} days left")
                elif len(cell_entities) > 1:
                    info_lines.append(f"Also here: {len(cell_entities) - 1} more")
                info_color = (236, 194, 143)
            elif inspected is not None:
                info_heading = inspected.name
                info_lines = [
                    f"Plant · {inspected.plant_type.title()}",
                    f"Health {inspected.health}   Water {inspected.water:.0f}",
                    f"Growth {inspected.growth:.1f}   Fruit {inspected.fruit_count}",
                ]
                if len(cell_entities) > 1:
                    info_lines.append(f"Also here: {len(cell_entities) - 1} more")
                info_color = (166, 218, 145)
            else:
                terrain_name = field.get_terrain(cell_x, cell_y)
                info_heading = terrain_name.replace("_", " ").title()
                soil_moisture = field.soil_moisture[cell_y][cell_x]
                info_lines = [
                    f"Terrain · ({cell_x}, {cell_y})",
                    f"Soil moisture {soil_moisture:.0f}%",
                    "Walkable" if field.is_walkable(cell_x, cell_y) else "Impassable",
                ]
                info_color = TERRAIN_COLORS.get(terrain_name, (210, 220, 205))

        screen.blit(event_font.render(info_heading[:28], True, info_color), (inspector_rect.x + 14, inspector_rect.y + 39))
        for index, line in enumerate(info_lines[:4]):
            screen.blit(muted_font.render(line[:34], True, (180, 196, 180)), (inspector_rect.x + 14, inspector_rect.y + 63 + index * 17))

        if paused:
            pause_overlay = pygame.Surface((map_width_px, field.max_column * TILE_SIZE), pygame.SRCALPHA)
            pause_overlay.fill((5, 12, 10, 115))
            screen.blit(pause_overlay, (0, 0))
            pause_label = sidebar_title_font.render("PAUSED", True, (245, 245, 230))
            pause_rect = pause_label.get_rect(center=(map_width_px // 2, field.max_column * TILE_SIZE // 2))
            screen.blit(pause_label, pause_rect)

        # Update the display
        pygame.display.flip()

        # Advance the simulation more slowly than the display refresh rate.
        while not paused and simulation_time >= simulation_tick_ms:
            before_entities = list(field.entities)
            before_actions = {
                id(entity): entity.action
                for entity in before_entities
                if isinstance(entity, Animal)
            }
            previous_weather = field.weather
            field.move_entities()

            def log_event(message, color=(217, 228, 211)):
                events.append((f"DAY {field.day:03d}", message, color))
                del events[:-40]

            if field.weather != previous_weather:
                if field.weather == "rain":
                    log_event("Rain started", (130, 193, 226))
                else:
                    log_event("The skies cleared", (217, 205, 140))

            old_animal_ids = {id(entity) for entity in before_entities if isinstance(entity, Animal)}
            for entity in field.entities:
                if isinstance(entity, Animal) and id(entity) not in old_animal_ids:
                    log_event(f"A {entity.name} was born", (166, 218, 145))

            remaining_ids = {id(entity) for entity in field.entities}
            for entity in before_entities:
                if isinstance(entity, Animal) and id(entity) not in remaining_ids:
                    log_event(f"{entity.name} died", (218, 132, 119))

            action_messages = {
                "fight": ("A fight broke out", (239, 148, 112)),
                "eat": ("An animal found food", (223, 196, 123)),
                "drink": ("An animal drank", (130, 193, 226)),
                "poop_seeds": ("Seeds were dispersed through feces", (166, 218, 145)),
                "pregnant": ("An animal is pregnant", (230, 167, 194)),
                "give_birth": ("A newborn arrived", (166, 218, 145)),
            }
            for entity in field.entities:
                if not isinstance(entity, Animal):
                    continue
                if entity.action != before_actions.get(id(entity)) and entity.action in action_messages:
                    message, color = action_messages[entity.action]
                    log_event(f"{entity.name}: {message}", color)

            simulation_time -= simulation_tick_ms


if __name__ == "__main__":
    main_simulation(entities)